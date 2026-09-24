from __future__ import annotations

"""Research-only multi-horizon matchday ablation.

The evaluator asks one narrow production question: does PIT-safe information
available at T-24h/T-6h/T-90m/T-60m add stable predictive value to the
current incumbent model when judged chronologically? It never publishes or
changes a production artifact.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src import matchday_intelligence_oos as matchday
from src import research_cycle_v4 as base
from src import uncertainty_dynamic_router_oos as uncertainty_router

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
RESULTS = ROOT / "results/matchday_horizon_research.json"
HORIZONS = (1440, 360, 90, 60)
ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _accepted_artifact(sport: str):
    path = ROOT / "models/research" / f"{sport}_current.joblib"
    if not path.is_file() or path.stat().st_size <= 0:
        return None, "missing_artifact"
    try:
        obj = joblib.load(path)
    except Exception as exc:
        return None, f"artifact_load_failed:{type(exc).__name__}"
    if str(obj.get("quality_status") or "") not in {
        "ACCEPTED_LOCKED_HOLDOUT",
        "ACCEPTED_AFTER_LOCKED_HOLDOUT",
    }:
        return None, f"artifact_not_accepted:{obj.get('quality_status')}"
    names = list(obj.get("model_names") or [])
    weights = obj.get("ensemble_weights") or {}
    if not names or not isinstance(weights, dict) or any(n not in weights for n in names):
        return None, "artifact_schema_invalid"
    if abs(sum(float(weights[n]) for n in names) - 1.0) > 1e-6:
        return None, "artifact_weight_sum_invalid"
    return obj, None


def _safe_logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(p / (1.0 - p))


def _candidate_pipeline():
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    C=0.25,
                    max_iter=2000,
                    random_state=20260924,
                ),
            ),
        ]
    )


def _weighted_prediction(fitted, names, weights, X):
    preds = []
    for name in names:
        model = fitted[name]
        preds.append(np.clip(model.predict_proba(X)[:, 1], 1e-6, 1.0 - 1e-6))
    arr = np.column_stack(preds)
    w = np.asarray([float(weights[name]) for name in names], dtype=float)
    return np.clip(arr @ w, 1e-6, 1.0 - 1e-6)


def _fit_incumbent_pool(feature_names, artifact, symmetric):
    names = list(artifact.get("model_names") or [])
    pool = base.pool(feature_names, symmetric=symmetric)
    missing = [n for n in names if n not in pool]
    if missing:
        raise RuntimeError("incumbent_models_missing:" + ",".join(missing))
    return names, pool


def _context_map(rows, horizon):
    subset = [(r[0], r[1]) for r in rows]
    contexts = matchday.build_matchday_context_rows(
        subset, DB, lead_minutes=int(horizon)
    )
    return {str(r[0]): np.asarray(ctx, dtype=float) for r, ctx in zip(rows, contexts)}


def _with_context(base_p, ctx):
    ctx = np.asarray(ctx, dtype=float)
    if ctx.ndim != 2 or ctx.shape[0] != len(base_p):
        raise ValueError("context shape mismatch")
    return np.column_stack([_safe_logit(base_p), ctx])


def _bootstrap_oos(fold_deltas, fold_groups):
    result = uncertainty_router.bootstrap_clustered_improvement(
        fold_deltas,
        fold_groups,
        seed=20260924,
        draws=1500,
    )
    return {
        "probability_improvement": float(result.get("probability_improvement", 0.0)),
        "p05_improvement": float(result.get("p05_improvement", float("-inf"))),
        "clusters": int(result.get("clusters", 0)),
    }


def _evaluate_sport(con, sport):
    artifact, reason = _accepted_artifact(sport)
    if artifact is None:
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": reason,
        }

    rows, features = base.build(con, sport)
    if len(rows) < 500:
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "insufficient_strict_pit_rows",
            "rows": len(rows),
        }

    artifact_features = list(artifact.get("features") or [])
    if not artifact_features or any(f not in set(features) for f in artifact_features):
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "incumbent_feature_schema_unavailable",
        }
    X = np.asarray(
        [[r[3].get(f, np.nan) for f in artifact_features] for r in rows],
        dtype=float,
    )
    y = np.asarray([r[2] for r in rows], dtype=int)
    sel = max(60, int(len(rows) * 0.78))
    start = max(80, int(sel * 0.70))
    if sel - start < 300 or len(rows) - sel < 60:
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "insufficient_oos_or_holdout",
            "rows": len(rows),
            "oos_rows": max(0, sel - start),
            "holdout_rows": max(0, len(rows) - sel),
        }

    names, model_pool = _fit_incumbent_pool(
        artifact_features,
        artifact,
        symmetric=sport in ("ufc", "rizin"),
    )
    weights = artifact.get("ensemble_weights") or {}
    fold_step = max(80, min(240, max(80, (sel - start) // 12)))
    folds = []
    fitted = {}

    for end in range(start, sel, fold_step):
        te = min(end + fold_step, sel)
        if te <= end or len(np.unique(y[:end])) < 2:
            continue
        fold_models = {}
        for name in names:
            model = model_pool[name]
            model.fit(X[:end], y[:end])
            fold_models[name] = model
        p = _weighted_prediction(fold_models, names, weights, X[end:te])
        folds.append(
            {
                "start": int(end),
                "end": int(te),
                "p": p,
                "y": y[end:te].copy(),
                "event_ids": [str(rows[i][0]) for i in range(end, te)],
            }
        )
        fitted = fold_models

    if len(folds) < 6:
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "insufficient_oos_folds",
            "folds": len(folds),
            "rows": len(rows),
        }

    all_holdout_models = {}
    for name in names:
        model = model_pool[name]
        model.fit(X[:sel], y[:sel])
        all_holdout_models[name] = model
    holdout_base = _weighted_prediction(
        all_holdout_models,
        names,
        weights,
        X[sel:],
    )

    oos_flat_p = np.concatenate([f["p"] for f in folds])
    oos_flat_y = np.concatenate([f["y"] for f in folds])
    oos_event_ids = np.concatenate([np.asarray(f["event_ids"], dtype=object) for f in folds])
    baseline_oos_metric = base.metric(oos_flat_y, oos_flat_p)

    # Build context only for OOS + frozen holdout rows. Early training rows do
    # not need matchday context, which keeps the evaluator bounded.
    eval_rows = rows[start:]
    contexts = {
        int(h): _context_map(eval_rows, int(h))
        for h in HORIZONS
    }

    results = {
        "sport": sport,
        "status": "EVALUATED",
        "rows": len(rows),
        "oos_rows": int(len(oos_flat_y)),
        "holdout_rows": int(len(y) - sel),
        "oos_folds": len(folds),
        "baseline_oos": baseline_oos_metric,
        "horizons": {},
        "policy": (
            "research_only; incumbent models refit chronologically; "
            "candidate sees only prior OOF predictions/context; "
            "frozen holdout is score-only; exact PIT source snapshots required"
        ),
    }

    for horizon in HORIZONS:
        ctx_map = contexts[int(horizon)]
        history_X = []
        history_y = []
        candidate_preds = []
        candidate_enabled = []
        fold_deltas = []
        fold_groups = []
        coverage_rows = 0
        total_rows = 0

        for fold in folds:
            ids = fold["event_ids"]
            ctx = np.asarray(
                [ctx_map[eid] for eid in ids],
                dtype=float,
            )
            total_rows += len(ctx)
            coverage_rows += int(np.isfinite(ctx).any(axis=1).sum())
            block_X = _with_context(fold["p"], ctx)
            model = None
            if len(history_y) >= 240 and len(np.unique(history_y)) == 2:
                model = _candidate_pipeline()
                try:
                    model.fit(np.asarray(history_X), np.asarray(history_y, dtype=int))
                except (ValueError, FloatingPointError):
                    model = None

            if model is None:
                cp = fold["p"].copy()
                enabled = np.zeros(len(cp), dtype=bool)
            else:
                cp = np.clip(model.predict_proba(block_X)[:, 1], 1e-6, 1.0 - 1e-6)
                enabled = np.ones(len(cp), dtype=bool)

            candidate_preds.append(cp)
            candidate_enabled.append(enabled)
            cand_loss = -(
                fold["y"] * np.log(cp)
                + (1 - fold["y"]) * np.log(1 - cp)
            )
            base_loss = -(
                fold["y"] * np.log(np.clip(fold["p"], 1e-6, 1 - 1e-6))
                + (1 - fold["y"]) * np.log(np.clip(1 - fold["p"], 1e-6, 1 - 1e-6))
            )
            fold_deltas.append(cand_loss - base_loss)
            fold_groups.append(np.asarray(ids, dtype=object))

            history_X.extend(block_X.tolist())
            history_y.extend(fold["y"].tolist())

        cp_oos = np.concatenate(candidate_preds)
        enabled_oos = np.concatenate(candidate_enabled)
        candidate_metric = base.metric(oos_flat_y, cp_oos)

        # Three non-overlapping chronological blocks at the fold level.
        block_metrics = []
        nblocks = min(3, len(folds))
        for fold_indices in np.array_split(np.arange(len(folds)), nblocks):
            yy = np.concatenate([folds[int(i)]["y"] for i in fold_indices])
            bb = np.concatenate([folds[int(i)]["p"] for i in fold_indices])
            cc = np.concatenate([candidate_preds[int(i)] for i in fold_indices])
            block_metrics.append(
                {
                    "baseline": base.metric(yy, bb),
                    "candidate": base.metric(yy, cc),
                    "logloss_improvement": float(
                        base.metric(yy, bb)["logloss"] - base.metric(yy, cc)["logloss"]
                    ),
                    "brier_improvement": float(
                        base.metric(yy, bb)["brier"] - base.metric(yy, cc)["brier"]
                    ),
                }
            )

        # Frozen holdout is never used to choose a candidate. It is evaluated
        # only after the OOS rolling stacker has observed the complete OOS set.
        holdout_context = np.asarray(
            [ctx_map[str(rows[i][0])] for i in range(sel, len(rows))],
            dtype=float,
        )
        holdout_X = _with_context(holdout_base, holdout_context)
        holdout_candidate = holdout_base.copy()
        if len(history_y) >= 240 and len(np.unique(history_y)) == 2:
            hold_model = _candidate_pipeline()
            try:
                hold_model.fit(np.asarray(history_X), np.asarray(history_y, dtype=int))
                holdout_candidate = np.clip(
                    hold_model.predict_proba(holdout_X)[:, 1],
                    1e-6,
                    1.0 - 1e-6,
                )
            except (ValueError, FloatingPointError):
                holdout_candidate = holdout_base.copy()

        boot = _bootstrap_oos(fold_deltas, fold_groups)
        oos_ll_delta = baseline_oos_metric["logloss"] - candidate_metric["logloss"]
        oos_brier_delta = baseline_oos_metric["brier"] - candidate_metric["brier"]
        positive_blocks = sum(
            1
            for b in block_metrics
            if b["logloss_improvement"] > 0.0
            and b["brier_improvement"] >= -0.001
        )
        coverage = coverage_rows / max(total_rows, 1)
        research_positive = bool(
            coverage >= 0.10
            and oos_ll_delta >= 0.001
            and oos_brier_delta >= -0.001
            and positive_blocks >= 2
            and boot["probability_improvement"] >= 0.90
            and boot["p05_improvement"] > 0.0
        )

        results["horizons"][str(horizon)] = {
            "lead_minutes": int(horizon),
            "context_coverage": float(coverage),
            "candidate_enabled_rows": int(enabled_oos.sum()),
            "baseline_oos": baseline_oos_metric,
            "candidate_oos": candidate_metric,
            "oos_logloss_improvement": float(oos_ll_delta),
            "oos_brier_improvement": float(oos_brier_delta),
            "holdout_baseline": base.metric(y[sel:], holdout_base),
            "holdout_candidate": base.metric(y[sel:], holdout_candidate),
            "block_results": block_metrics,
            "cluster_bootstrap": boot,
            "positive_block_count": int(positive_blocks),
            "research_positive": research_positive,
            "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        }

    return results


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    try:
        sports = list(ACTIVE_SPORTS)
        out = {
            "generated_at_utc": _utc(),
            "status": "EVALUATED",
            "horizons": list(HORIZONS),
            "sports": [_evaluate_sport(con, sport) for sport in sports],
            "policy": (
                "No production model, weight, threshold or probability is changed "
                "by this evaluator. Positive findings remain research-only until "
                "the existing PIT/OOS/frozen-holdout release gate passes."
            ),
        }
    finally:
        con.close()
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
