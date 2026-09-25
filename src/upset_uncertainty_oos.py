from __future__ import annotations

"""Research-only race/event-level upset and uncertainty diagnostics.

The layer predicts the probability that the incumbent's high-confidence call
will be wrong. It is trained strictly predict-then-update on chronological OOF
folds and is never allowed to alter production artifacts or current probabilities
automatically.

The research target is deliberately operational rather than causal:
an "upset-risk event" is a high-confidence incumbent prediction that later
misses. This makes the layer useful for detecting cases where the incumbent may
be overconfident, while keeping the label unavailable at prediction time.
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Sequence

import joblib
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

from src import matchday_intelligence_oos as matchday
from src import research_cycle_v4 as base
from src import uncertainty_dynamic_router_oos as uncertainty_router

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
RESULTS = ROOT / "results/upset_uncertainty_oos.json"
ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")

EPS = 1e-6
CONFIDENCE_FLOOR = 0.65
RISK_THRESHOLD = 0.55
POLICY_STRENGTHS = (0.20, 0.35, 0.50)


def _clip(p):
    return np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)


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
    if not names or not isinstance(weights, dict):
        return None, "artifact_schema_invalid"
    if any(n not in weights for n in names):
        return None, "artifact_weight_missing"
    w = np.asarray([float(weights[n]) for n in names], dtype=float)
    if not np.isfinite(w).all() or w.sum() <= 0:
        return None, "artifact_weight_invalid"
    return obj, None


def _weighted_prediction(fitted, names, weights, X):
    preds = []
    for name in names:
        p = np.asarray(fitted[name].predict_proba(X))
        if p.ndim != 2 or p.shape[1] != 2:
            raise RuntimeError(f"unsupported_binary_model:{name}")
        preds.append(_clip(p[:, 1]))
    arr = np.column_stack(preds)
    w = np.asarray([float(weights[name]) for name in names], dtype=float)
    w /= w.sum()
    return _clip(arr @ w), arr


def _high_confidence_mask(p):
    p = _clip(p)
    return np.maximum(p, 1.0 - p) >= CONFIDENCE_FLOOR


def _risk_target(p, y):
    p = _clip(p)
    y = np.asarray(y, dtype=int)
    confident = _high_confidence_mask(p)
    pred = (p >= 0.5).astype(int)
    miss = pred != y
    return (confident & miss).astype(int)


def _feature_matrix(baseline_p, expert_p, context, X):
    p = _clip(baseline_p)
    ep = _clip(expert_p)
    ctx = np.asarray(context, dtype=float)
    X = np.asarray(X, dtype=float)
    if len(p) != len(ctx) or len(p) != len(X) or ep.shape[0] != len(p):
        raise ValueError("upset feature row mismatch")

    entropy = -(p * np.log(p) + (1.0 - p) * np.log(1.0 - p))
    disagreement = np.std(ep, axis=1)
    pair_gap = np.max(ep, axis=1) - np.min(ep, axis=1)
    mean_expert_entropy = np.mean(
        -(ep * np.log(ep) + (1.0 - ep) * np.log(1.0 - ep)),
        axis=1,
    )
    epistemic_proxy = np.maximum(entropy - mean_expert_entropy, 0.0)
    confident_margin = np.abs(p - 0.5)
    missing_fraction = 1.0 - np.mean(np.isfinite(X), axis=1)

    return np.column_stack(
        [
            p,
            confident_margin,
            entropy,
            disagreement,
            pair_gap,
            mean_expert_entropy,
            epistemic_proxy,
            missing_fraction,
            ctx,
        ]
    )


def _risk_pipeline():
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    C=0.25,
                    max_iter=2000,
                    # Preserve the empirical event prior so the risk score can
                    # be thresholded as a probability rather than a rebalanced
                    # classifier score. Calibration is evaluated separately.
                    class_weight=None,
                    random_state=20260925,
                ),
            ),
        ]
    )


def _policy_probability(p, risk, strength):
    p = _clip(p)
    risk = np.clip(np.asarray(risk, dtype=float), 0.0, 1.0)
    high_conf = np.maximum(p, 1.0 - p) >= CONFIDENCE_FLOOR
    active = high_conf & (risk >= RISK_THRESHOLD)
    out = p.copy()
    out[active] = (1.0 - float(strength)) * p[active] + float(strength) * 0.5
    return _clip(out)

def _dissent_probability(p, expert_p, weights):
    """Weighted probability of experts whose class disagrees with the incumbent."""
    p = _clip(p)
    ep = _clip(expert_p)
    w = np.asarray(weights, dtype=float)
    if ep.ndim != 2 or ep.shape[0] != len(p):
        raise ValueError("dissent expert shape mismatch")
    if w.ndim != 1 or len(w) != ep.shape[1] or not np.isfinite(w).all() or w.sum() <= 0:
        w = np.full(ep.shape[1], 1.0 / ep.shape[1], dtype=float)
    else:
        w = w / w.sum()
    incumbent_class = (p >= 0.5).astype(int)
    dissent = (ep >= 0.5).astype(int) != incumbent_class[:, None]
    denominator = np.sum(w[None, :] * dissent, axis=1)
    numerator = np.sum(ep * w[None, :] * dissent, axis=1)
    available = denominator > 0.0
    out = p.copy()
    out[available] = numerator[available] / denominator[available]
    return _clip(out), available


def _policy_dissent(p, risk, expert_p, weights, strength):
    """Consult the opposing expert side only when risk is high and dissent is material."""
    p = _clip(p)
    risk = np.clip(np.asarray(risk, dtype=float), 0.0, 1.0)
    dissent_p, available = _dissent_probability(p, expert_p, weights)
    high_conf = np.maximum(p, 1.0 - p) >= CONFIDENCE_FLOOR
    active = (
        high_conf
        & (risk >= RISK_THRESHOLD)
        & available
        & (np.abs(dissent_p - 0.5) >= 0.08)
    )
    out = p.copy()
    out[active] = (1.0 - float(strength)) * p[active] + float(strength) * dissent_p[active]
    return _clip(out), active


def _risk_diagnostics(y, p, risk):
    target = _risk_target(p, y)
    metrics = {
        "risk_target_rows": int(len(target)),
        "positive_risk_events": int(target.sum()),
        "positive_rate": float(target.mean()) if len(target) else 0.0,
        "risk_probability_mean": float(np.mean(risk)) if len(risk) else 0.0,
    }
    if len(np.unique(target)) == 2:
        try:
            metrics["roc_auc"] = float(roc_auc_score(target, risk))
        except ValueError:
            metrics["roc_auc"] = None
        metrics["risk_brier"] = float(base.metric(target, risk)["brier"])
        metrics["risk_ece"] = float(base.metric(target, risk)["ece"])
        order = np.argsort(risk)
        q = max(1, len(order) // 4)
        low = target[order[:q]]
        high = target[order[-q:]]
        metrics["bottom_quartile_miss_rate"] = float(low.mean())
        metrics["top_quartile_miss_rate"] = float(high.mean())
        metrics["top_vs_bottom_miss_lift"] = (
            float(high.mean() / low.mean()) if low.mean() > 0 else None
        )
    else:
        metrics.update(
            {
                "roc_auc": None,
                "risk_brier": None,
                "risk_ece": None,
                "bottom_quartile_miss_rate": None,
                "top_quartile_miss_rate": None,
                "top_vs_bottom_miss_lift": None,
            }
        )
    return metrics


def _fit_holdout_risk_model(pre_features, pre_target, holdout_features):
    if len(pre_target) < 240 or len(np.unique(pre_target)) != 2:
        return np.full(len(holdout_features), 0.5, dtype=float), False
    model = _risk_pipeline()
    try:
        model.fit(pre_features, pre_target)
        risk = model.predict_proba(holdout_features)[:, 1]
        return np.clip(risk, EPS, 1.0 - EPS), True
    except (ValueError, FloatingPointError):
        return np.full(len(holdout_features), 0.5, dtype=float), False


def _evaluate_sport(con, sport):
    artifact, reason = _accepted_artifact(sport)
    if artifact is None:
        return {"sport": sport, "status": "DEFERRED", "reason": reason}

    rows, feature_names = base.build(con, sport)
    if len(rows) < 500:
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "insufficient_strict_pit_rows",
            "rows": len(rows),
        }

    artifact_features = list(artifact.get("features") or [])
    available = set(feature_names)
    if not artifact_features or any(f not in available for f in artifact_features):
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

    names = list(artifact.get("model_names") or [])
    weights = artifact.get("ensemble_weights") or {}
    pool = base.pool(artifact_features, symmetric=sport in ("ufc", "rizin"))
    missing = [n for n in names if n not in pool]
    if missing:
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "incumbent_models_missing:" + ",".join(missing),
        }

    eval_rows = [(str(r[0]), str(r[1])) for r in rows[start:]]
    contexts_list = matchday.build_matchday_context_rows(
        eval_rows, DB, lead_minutes=60
    )
    context_map = {
        str(r[0]): np.asarray(c, dtype=float)
        for r, c in zip(rows[start:], contexts_list)
    }

    fold_step = max(80, min(240, max(80, (sel - start) // 12)))
    folds = []
    history_meta_x = []
    history_target = []
    history_high_conf_x = []
    history_high_conf_target = []

    for end in range(start, sel, fold_step):
        te = min(end + fold_step, sel)
        if te <= end or len(np.unique(y[:end])) < 2:
            continue

        fitted = {}
        for name in names:
            model = pool[name]
            model.fit(X[:end], y[:end])
            fitted[name] = model

        p, ep = _weighted_prediction(fitted, names, weights, X[end:te])
        ids = [str(rows[i][0]) for i in range(end, te)]
        ctx = np.asarray([context_map[eid] for eid in ids], dtype=float)
        features = _feature_matrix(p, ep, ctx, X[end:te])
        target = _risk_target(p, y[end:te])

        risk_model = None
        if (
            len(history_high_conf_target) >= 120
            and len(np.unique(history_high_conf_target)) == 2
        ):
            risk_model = _risk_pipeline()
            try:
                risk_model.fit(
                    np.asarray(history_high_conf_x),
                    np.asarray(history_high_conf_target),
                )
            except (ValueError, FloatingPointError):
                risk_model = None

        test_conf = _high_confidence_mask(p)
        risk = np.full(len(features), 0.5, dtype=float)
        if risk_model is None:
            enabled = False
        else:
            try:
                risk[test_conf] = np.clip(
                    risk_model.predict_proba(features[test_conf])[:, 1],
                    EPS,
                    1.0 - EPS,
                )
                enabled = True
            except (ValueError, FloatingPointError):
                enabled = False

        folds.append(
            {
                "start": int(end),
                "end": int(te),
                "p": p,
                "risk": risk,
                "y": y[end:te].copy(),
                "risk_target": target,
                "feature_rows": features,
                "expert_p": ep,
                "enabled": enabled,
                "event_ids": ids,
            }
        )
        history_meta_x.extend(features.tolist())
        history_target.extend(target.tolist())
        if test_conf.any():
            history_high_conf_x.extend(features[test_conf].tolist())
            history_high_conf_target.extend(target[test_conf].tolist())

    if len(folds) < 6:
        return {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "insufficient_oos_folds",
            "folds": len(folds),
            "rows": len(rows),
        }

    oos_y = np.concatenate([f["y"] for f in folds])
    oos_p = np.concatenate([f["p"] for f in folds])
    oos_risk = np.concatenate([f["risk"] for f in folds])
    baseline = base.metric(oos_y, oos_p)

    policy_results = {}
    weights_vec = np.asarray([float(weights[name]) for name in names], dtype=float)
    if not np.isfinite(weights_vec).all() or weights_vec.sum() <= 0:
        weights_vec = np.full(len(names), 1.0 / len(names), dtype=float)
    else:
        weights_vec /= weights_vec.sum()

    def _record_policy(key, strength, kind, predictions, deltas, block_metrics, active_rows, extra=None):
        cp = np.concatenate(predictions)
        m = base.metric(oos_y, cp)
        clustered = uncertainty_router.bootstrap_clustered_improvement(
            deltas,
            [np.asarray(f["event_ids"], dtype=object) for f in folds],
            seed=20260925,
            draws=1500,
        )
        positive_blocks = sum(
            1
            for b in block_metrics
            if b["logloss_improvement"] > 0.0 and b["brier_improvement"] >= -0.001
        )
        payload = {
            "strength": float(strength),
            "kind": kind,
            "oos": m,
            "oos_logloss_improvement": float(baseline["logloss"] - m["logloss"]),
            "oos_brier_improvement": float(baseline["brier"] - m["brier"]),
            "oos_accuracy_improvement": float(m["accuracy"] - baseline["accuracy"]),
            "ece_change": float(m["ece"] - baseline["ece"]),
            "positive_block_count": int(positive_blocks),
            "block_results": block_metrics,
            "cluster_bootstrap": clustered,
            "active_rows": int(active_rows),
        }
        if extra:
            payload.update(extra)
        policy_results[key] = payload

    for strength in POLICY_STRENGTHS:
        key = f"shrink_{strength:.2f}"
        preds, deltas, block_metrics = [], [], []
        active_rows = 0
        for f in folds:
            adj = _policy_probability(f["p"], f["risk"], strength)
            preds.append(adj)
            active = (
                (np.maximum(f["p"], 1.0 - f["p"]) >= CONFIDENCE_FLOOR)
                & (f["risk"] >= RISK_THRESHOLD)
            )
            active_rows += int(active.sum())
            loss_base = -(f["y"] * np.log(_clip(f["p"])) + (1 - f["y"]) * np.log(1 - _clip(f["p"])))
            loss_adj = -(f["y"] * np.log(_clip(adj)) + (1 - f["y"]) * np.log(1 - _clip(adj)))
            deltas.append(loss_base - loss_adj)
        for idxs in np.array_split(np.arange(len(folds)), min(3, len(folds))):
            yy = np.concatenate([folds[int(i)]["y"] for i in idxs])
            bb = np.concatenate([folds[int(i)]["p"] for i in idxs])
            cc = np.concatenate([preds[int(i)] for i in idxs])
            block_metrics.append({
                "baseline": base.metric(yy, bb),
                "candidate": base.metric(yy, cc),
                "logloss_improvement": float(base.metric(yy, bb)["logloss"] - base.metric(yy, cc)["logloss"]),
                "brier_improvement": float(base.metric(yy, bb)["brier"] - base.metric(yy, cc)["brier"]),
                "accuracy_improvement": float(np.mean((cc >= 0.5) == yy) - np.mean((bb >= 0.5) == yy)),
            })
        _record_policy(key, strength, "probability_shrinkage", preds, deltas, block_metrics, active_rows)

    for strength in POLICY_STRENGTHS:
        key = f"dissent_{strength:.2f}"
        preds, deltas, block_metrics = [], [], []
        active_rows = 0
        for f in folds:
            adj, active = _policy_dissent(
                f["p"], f["risk"], f["expert_p"], weights_vec, strength
            )
            preds.append(adj)
            active_rows += int(active.sum())
            loss_base = -(f["y"] * np.log(_clip(f["p"])) + (1 - f["y"]) * np.log(1 - _clip(f["p"])))
            loss_adj = -(f["y"] * np.log(_clip(adj)) + (1 - f["y"]) * np.log(1 - _clip(adj)))
            deltas.append(loss_base - loss_adj)
        for idxs in np.array_split(np.arange(len(folds)), min(3, len(folds))):
            yy = np.concatenate([folds[int(i)]["y"] for i in idxs])
            bb = np.concatenate([folds[int(i)]["p"] for i in idxs])
            cc = np.concatenate([
                _policy_dissent(
                    folds[int(i)]["p"], folds[int(i)]["risk"],
                    folds[int(i)]["expert_p"], weights_vec, strength
                )[0]
                for i in idxs
            ])
            block_metrics.append({
                "baseline": base.metric(yy, bb),
                "candidate": base.metric(yy, cc),
                "logloss_improvement": float(base.metric(yy, bb)["logloss"] - base.metric(yy, cc)["logloss"]),
                "brier_improvement": float(base.metric(yy, bb)["brier"] - base.metric(yy, cc)["brier"]),
                "accuracy_improvement": float(np.mean((cc >= 0.5) == yy) - np.mean((bb >= 0.5) == yy)),
            })
        _record_policy(
            key, strength, "dissent_rescue", preds, deltas, block_metrics,
            active_rows,
            extra={"selection_requires_accuracy_improvement": True},
        )

    ranked = sorted(
        policy_results.items(),
        key=lambda item: (
            -float(item[1]["oos_logloss_improvement"]),
            -float(item[1]["oos_accuracy_improvement"]),
            -float(item[1]["oos_brier_improvement"]),
            float(item[1]["ece_change"]),
        ),
    )
    selected_key = "none"
    selected_strength = 0.0
    for key, r in ranked:
        accuracy_ok = (
            r.get("kind") != "dissent_rescue"
            or r.get("oos_accuracy_improvement", 0.0) > 0.0
        )
        if (
            r["oos_logloss_improvement"] > 0.0
            and r["oos_brier_improvement"] >= -0.001
            and r["positive_block_count"] >= 2
            and accuracy_ok
        ):
            selected_key = key
            selected_strength = float(r["strength"])
            break

    final_pre_x = np.asarray(history_high_conf_x, dtype=float)
    final_pre_target = np.asarray(history_high_conf_target, dtype=int)

    holdout_fitted = {}
    for name in names:
        model = pool[name]
        model.fit(X[:sel], y[:sel])
        holdout_fitted[name] = model
    holdout_base, holdout_ep = _weighted_prediction(
        holdout_fitted, names, weights, X[sel:]
    )
    holdout_ids = [str(rows[i][0]) for i in range(sel, len(rows))]
    holdout_ctx = np.asarray([context_map[eid] for eid in holdout_ids], dtype=float)
    holdout_features = _feature_matrix(holdout_base, holdout_ep, holdout_ctx, X[sel:])
    holdout_conf = _high_confidence_mask(holdout_base)
    holdout_risk = np.full(len(holdout_features), 0.5, dtype=float)
    holdout_risk_conf, risk_enabled = _fit_holdout_risk_model(
        final_pre_x,
        final_pre_target,
        holdout_features[holdout_conf],
    )
    holdout_risk[holdout_conf] = holdout_risk_conf
    if selected_key.startswith("dissent_"):
        holdout_candidate, _ = _policy_dissent(
            holdout_base, holdout_risk, holdout_ep, weights_vec, selected_strength
        )
    else:
        holdout_candidate = (
            _policy_probability(holdout_base, holdout_risk, selected_strength)
            if selected_key != "none"
            else holdout_base.copy()
        )

    high_conf = np.maximum(oos_p, 1.0 - oos_p) >= CONFIDENCE_FLOOR
    high_conf_p = oos_p[high_conf]
    high_conf_y = oos_y[high_conf]
    if selected_key.startswith("dissent_"):
        high_expert = np.concatenate([f["expert_p"] for f in folds], axis=0)[high_conf]
        high_conf_candidate, _ = _policy_dissent(
            high_conf_p, oos_risk[high_conf], high_expert, weights_vec, selected_strength
        )
    else:
        high_conf_candidate = (
            _policy_probability(high_conf_p, oos_risk[high_conf], selected_strength)
            if selected_key != "none"
            else high_conf_p.copy()
        )

    result = {
        "sport": sport,
        "status": "EVALUATED",
        "rows": int(len(rows)),
        "oos_rows": int(len(oos_y)),
        "holdout_rows": int(len(y) - sel),
        "oos_folds": int(len(folds)),
        "baseline_oos": baseline,
        "selected_policy": selected_key,
        "selected_strength": float(selected_strength),
        "policy_grid": policy_results,
        "risk_diagnostics_oos": _risk_diagnostics(oos_y, oos_p, oos_risk),
        "high_confidence_oos": {
            "rows": int(high_conf.sum()),
            "baseline": base.metric(high_conf_y, high_conf_p) if len(high_conf_y) else None,
            "candidate": base.metric(high_conf_y, high_conf_candidate) if len(high_conf_y) else None,
            "risk_diagnostics": _risk_diagnostics(high_conf_y, high_conf_p, oos_risk[high_conf])
            if len(high_conf_y) else None,
        },
        "holdout": {
            "baseline": base.metric(y[sel:], holdout_base),
            "candidate": base.metric(y[sel:], holdout_candidate),
            "logloss_improvement": float(base.metric(y[sel:], holdout_base)["logloss"] - base.metric(y[sel:], holdout_candidate)["logloss"]),
            "brier_improvement": float(base.metric(y[sel:], holdout_base)["brier"] - base.metric(y[sel:], holdout_candidate)["brier"]),
            "ece_change": float(base.metric(y[sel:], holdout_candidate)["ece"] - base.metric(y[sel:], holdout_base)["ece"]),
            "risk_model_enabled": bool(risk_enabled),
            "risk_diagnostics": _risk_diagnostics(y[sel:], holdout_base, holdout_risk),
        },
        "policy": {
            "target": "high-confidence incumbent miss",
            "risk_model_training_population": "high-confidence cases only",
            "confidence_floor": CONFIDENCE_FLOOR,
            "risk_threshold": RISK_THRESHOLD,
            "candidate_strengths": list(POLICY_STRENGTHS),
            "selection_scope": "chronological_pre_holdout_oos_only",
            "holdout_scope": "frozen_score_only; no label updates",
            "production_effect": "none",
        },
        "pit": {
            "feature_rows": "strict_pit_base.build",
            "matchday_context_lead_minutes": 60,
            "label_only": "incumbent-miss target is used after outcomes are known",
        },
    }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=ACTIVE_SPORTS)
    args = ap.parse_args()
    if not DB.is_file():
        raise SystemExit(f"FAIL_CLOSED_DB_MISSING:{DB}")
    con = sqlite3.connect(DB)
    try:
        sports = [args.sport] if args.sport else list(ACTIVE_SPORTS)
        out = {
            "status": "EVALUATED",
            "sports": [_evaluate_sport(con, sport) for sport in sports],
            "generated_by": "src/upset_uncertainty_oos.py",
            "production_model_changed": False,
            "policy": (
                "research-only; prediction features are pre-event PIT-safe; "
                "risk labels are used only after outcomes and only for later folds; "
                "no automatic production promotion"
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
