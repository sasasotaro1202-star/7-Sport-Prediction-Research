from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import joblib
import numpy as np

from src import research_cycle_v4 as base
from src.competition_profiles import build_segment_candidates, resolve_research_profile

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
POLICY_PATH = ROOT / "config/COMPETITION_ROUTING_POLICY.json"
OUT = ROOT / "results/research/competition_routes.json"
ARTIFACT_DIR = ROOT / "models/competition"


def _load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _safe(value):
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(x) for x in value]
    return value


def _git_sha() -> str:
    env_sha = str(os.getenv("GITHUB_SHA") or "").strip()
    if env_sha:
        return env_sha
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "UNKNOWN_UNVERIFIED"


def _artifact_name(segment_id: str) -> str:
    return f"route_{hashlib.sha256(segment_id.encode('utf-8')).hexdigest()[:16]}.joblib"


def _periods(items: list[dict]) -> list[str]:
    seasons = sorted({str(x.get("season")) for x in items if x.get("season")})
    if seasons:
        return seasons
    return sorted({str(x["time"])[:4] for x in items if x.get("time")})


def _load_event_metadata(con: sqlite3.Connection, sport: str) -> dict[str, dict[str, str]]:
    """Load competition metadata from the canonical v45 event schema."""
    return {
        str(eid): {
            "event_id": str(eid),
            "competition_id": str(comp or ""),
            "season": str(season or ""),
            "stage": str(stage or ""),
            "time": str(t or ""),
        }
        for eid, comp, season, stage, t in con.execute(
            "SELECT event_id,competition_id,season,stage,event_time_utc FROM event WHERE sport=?",
            (sport,),
        ).fetchall()
    }


def _fit_oos(items: list[dict], features: list[str], candidates: list[str], minimums: dict, symmetric: bool):
    items = sorted(items, key=lambda x: (x["time"], x["event_id"]))
    n = len(items)
    canonical_ids = {str(x.get("canonical_competition_id") or "") for x in items}
    segment_ids = {str(x.get("segment_id") or "") for x in items}
    if len(canonical_ids) != 1 or not next(iter(canonical_ids), ""):
        return {"status": "IDENTITY_INCONSISTENT", "rows": n, "canonical_competition_ids": sorted(canonical_ids)}
    if len(segment_ids) != 1 or not next(iter(segment_ids), ""):
        return {"status": "SEGMENT_IDENTITY_INCONSISTENT", "rows": n, "segment_ids": sorted(segment_ids)}
    holdout_n = max(int(minimums.get("holdout_rows", 30)), int(np.ceil(n * 0.20)))
    holdout_n = min(holdout_n, n)
    pre_n = n - holdout_n
    train_min = int(minimums.get("pre_holdout_train_rows", 90))
    folds_target = int(minimums.get("folds", 4))
    min_test = int(minimums.get("min_test_rows_per_fold", 15))
    if (
        n < int(minimums.get("rows", 180))
        or pre_n < train_min + folds_target * min_test
        or len(set(x["label"] for x in items)) < 2
        or len(_periods(items)) < int(minimums.get("periods", 2))
    ):
        return {"status": "INSUFFICIENT_DATA", "rows": n, "pre_holdout_rows": pre_n, "holdout_rows": holdout_n, "periods": _periods(items)}

    X = np.asarray([[x["features"].get(f, np.nan) for f in features] for x in items], dtype=float)
    y = np.asarray([int(x["label"]) for x in items], dtype=int)
    pre_X, pre_y = X[:pre_n], y[:pre_n]
    hold_X, hold_y = X[pre_n:], y[pre_n:]
    if len(np.unique(hold_y)) < 2 or len(np.unique(pre_y)) < 2:
        return {"status": "INVALID_HOLDOUT_LABEL_DIVERSITY", "rows": n, "pre_holdout_rows": pre_n, "holdout_rows": holdout_n}

    eval_idx = np.arange(train_min, pre_n)
    blocks = [b for b in np.array_split(eval_idx, folds_target) if len(b) >= min_test]
    if len(blocks) < folds_target:
        return {"status": "INSUFFICIENT_OOS_FOLDS", "rows": n, "folds": len(blocks)}

    pool = base.pool(features, symmetric=symmetric)
    names = [name for name in candidates if name in pool]
    if "logistic" not in names:
        return {"status": "BASELINE_MISSING", "rows": n}

    results = {}
    fold_details = {}
    for name in names:
        fold_metrics = []
        for block in blocks:
            start = int(block[0])
            end = int(block[-1]) + 1
            if len(np.unique(pre_y[:start])) < 2 or len(np.unique(pre_y[start:end])) < 2:
                continue
            model = base.pool(features, symmetric=symmetric)[name]
            model.fit(pre_X[:start], pre_y[:start])
            p = np.clip(model.predict_proba(pre_X[start:end])[:, 1], 1e-6, 1 - 1e-6)
            m = base.metric(pre_y[start:end], p)
            m["oos_start"] = items[start]["time"]
            m["oos_end"] = items[end - 1]["time"]
            fold_metrics.append(m)
        if len(fold_metrics) >= folds_target:
            results[name] = {
                "logloss": float(np.mean([m["logloss"] for m in fold_metrics])),
                "brier": float(np.mean([m["brier"] for m in fold_metrics])),
                "ece": float(np.mean([m["ece"] for m in fold_metrics])),
                "accuracy": float(np.mean([m["accuracy"] for m in fold_metrics])),
                "folds": len(fold_metrics),
                "fold_logloss_std": float(np.std([m["logloss"] for m in fold_metrics])),
                "folds_detail": fold_metrics,
            }
            fold_details[name] = fold_metrics

    if "logistic" not in results:
        return {"status": "INSUFFICIENT_VALID_CANDIDATES", "rows": n, "candidate_results": results}

    baseline = results["logistic"]
    best = min(results, key=lambda name: (results[name]["logloss"], results[name]["brier"], results[name]["ece"]))
    candidate = results[best]
    common_keys = [
        (str(m["oos_start"]), str(m["oos_end"]))
        for m in baseline["folds_detail"]
        if any((str(c["oos_start"]), str(c["oos_end"])) == (str(m["oos_start"]), str(m["oos_end"])) for c in candidate["folds_detail"])
    ]
    candidate_map = {(str(m["oos_start"]), str(m["oos_end"])): m for m in candidate["folds_detail"]}
    baseline_map = {(str(m["oos_start"]), str(m["oos_end"])): m for m in baseline["folds_detail"]}
    non_worse = float(np.mean([
        candidate_map[key]["logloss"] <= baseline_map[key]["logloss"] + 1e-12
        for key in common_keys
    ])) if common_keys else 0.0
    rel_improvement = float((baseline["logloss"] - candidate["logloss"]) / max(abs(baseline["logloss"]), 1e-12))

    selected = (
        best != "logistic"
        and len(common_keys) >= folds_target
        and rel_improvement >= float(_load_policy()["selection"]["min_relative_logloss_improvement"])
        and non_worse >= float(_load_policy()["selection"]["min_folds_not_worse"])
        and candidate["brier"] <= baseline["brier"] + 1e-12
        and candidate["ece"] <= baseline["ece"] + 1e-12
    )
    if not selected:
        return {
            "status": "OOS_NO_ROUTE",
            "rows": n,
            "pre_holdout_rows": pre_n,
            "holdout_rows": holdout_n,
            "periods": _periods(items),
            "baseline_model": "logistic",
            "selected_research_candidate": best,
            "baseline_logloss": baseline["logloss"],
            "candidate_logloss": candidate["logloss"],
            "relative_logloss_improvement": rel_improvement,
            "fold_non_worse_rate": non_worse,
            "candidate_results": results,
            "holdout_used_for_selection": False,
        }

    # Lock the candidate before looking at frozen-holdout labels.
    incumbent = pool["logistic"]
    challenger = pool[best]
    incumbent.fit(pre_X, pre_y)
    challenger.fit(pre_X, pre_y)
    p_base = np.clip(incumbent.predict_proba(hold_X)[:, 1], 1e-6, 1 - 1e-6)
    p_chal = np.clip(challenger.predict_proba(hold_X)[:, 1], 1e-6, 1 - 1e-6)
    hold_base = base.metric(hold_y, p_base)
    hold_chal = base.metric(hold_y, p_chal)

    base_losses = -(hold_y * np.log(p_base) + (1 - hold_y) * np.log(1 - p_base))
    chal_losses = -(hold_y * np.log(p_chal) + (1 - hold_y) * np.log(1 - p_chal))
    improvements = base_losses - chal_losses
    rng_seed = int(hashlib.sha256((str(items[0]["event_id"]) + best).encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(rng_seed)
    draws = []
    samples = int(_load_policy()["selection"].get("bootstrap_samples", 600))
    for _ in range(max(100, samples)):
        idx = rng.integers(0, len(improvements), len(improvements))
        draws.append(float(np.mean(improvements[idx])))
    bootstrap = {
        "samples": len(draws),
        "p05_improvement": float(np.percentile(draws, 5)),
        "median_improvement": float(np.percentile(draws, 50)),
        "probability_improvement": float(np.mean(np.asarray(draws) > 0.0)),
    }

    holdout = {
        "baseline": hold_base,
        "challenger": hold_chal,
        "logloss_improvement": float(hold_base["logloss"] - hold_chal["logloss"]),
        "brier_improvement": float(hold_base["brier"] - hold_chal["brier"]),
        "ece_change": float(hold_chal["ece"] - hold_base["ece"]),
        "bootstrap": bootstrap,
        "n": int(len(hold_y)),
    }
    sel_cfg = _load_policy()["selection"]
    accepted = (
        holdout["n"] >= int(_load_policy()["minimums"]["holdout_rows"])
        and holdout["logloss_improvement"] >= 0.0
        and holdout["brier_improvement"] >= -float(sel_cfg["holdout_brier_tolerance"])
        and holdout["ece_change"] <= float(sel_cfg["holdout_ece_tolerance"])
        and bootstrap["probability_improvement"] >= float(sel_cfg["bootstrap_probability_improvement"])
        and bootstrap["p05_improvement"] > 0.0
    )
    if not accepted:
        return {
            "status": "HOLDOUT_NO_ROUTE",
            "rows": n,
            "pre_holdout_rows": pre_n,
            "holdout_rows": holdout_n,
            "periods": _periods(items),
            "selected_research_candidate": best,
            "relative_logloss_improvement": rel_improvement,
            "fold_non_worse_rate": non_worse,
            "holdout": holdout,
            "holdout_used_for_selection": False,
        }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_name = _artifact_name(items[0]["segment_id"])
    artifact_path = ARTIFACT_DIR / artifact_name
    # Refit the accepted competition-specific estimator only on labels strictly
    # before the frozen holdout. The holdout is score-only and never enters training.
    challenger.fit(pre_X, pre_y)
    joblib.dump(challenger, artifact_path)
    rel_artifact = str(artifact_path.relative_to(ROOT))
    meta = {
        "route_version": "hierarchical-competition-production-route-v2",
        "profile_id": items[0]["profile_id"],
        "segment_id": items[0]["segment_id"],
        "segment_specificity": int(items[0].get("segment_specificity", 0)),
        "segment_context": dict(items[0].get("segment_context") or {}),
        "competition_id": items[0]["competition_id"],
        "canonical_competition_id": items[0]["canonical_competition_id"],
        "sport": items[0]["sport"],
        "season_scope": _periods(items),
        "model_name": best,
        "model_version": f"competition-route-{hashlib.sha256((items[0]["profile_id"] + "|" + best + "|" + items[pre_n - 1]["time"]).encode("utf-8")).hexdigest()[:16]}",
        "strategy": "competition_specific_model",
        "model_scope": "competition_specific;frozen_holdout_accepted",
        "feature_names": list(features),
        "feature_version": "competition-route-base-features",
        "training_cutoff_utc": items[pre_n - 1]["time"],
        "git_commit_sha": _git_sha(),
        "artifact_path": rel_artifact,
        "quality_status": "ACCEPTED_LOCKED_HOLDOUT",
        "holdout_used_for_selection": False,
        "oos": {
            "rows": pre_n,
            "baseline_logloss": baseline["logloss"],
            "candidate_logloss": candidate["logloss"],
            "relative_logloss_improvement": rel_improvement,
            "fold_non_worse_rate": non_worse,
        },
        "holdout": holdout,
        "pit_status": "REQUIRED_CLEAN_BY_PRODUCTION_GATE",
        "fallback": "sport_incumbent",
    }
    return meta


def build_route_registry(db_path: Path | None = None, sports: list[str] | None = None) -> dict:
    policy = _load_policy()
    db_path = Path(db_path or DB).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    con = sqlite3.connect(db_path)
    try:
        scope = json.loads((ROOT / "config/PROJECT_SCOPE_POLICY.json").read_text(encoding="utf-8"))
        active = list(scope.get("active_prediction_scope") or [])
        if sports:
            active = [s for s in active if s in set(sports)]
        report = {
            "version": "competition-specific-production-route-v1",
            "status": "READY",
            "production_scope": active,
            "policy": policy,
            "routes": {},
            "blocked": {},
            "pit_gate": {"required": bool(policy["selection"]["require_pit_clean_before_route"]), "status": "PENDING_PRODUCTION_INDEPENDENT_AUDIT"},
            "source_git_sha": _git_sha(),
        }
        pit_bad = int(con.execute(
            "SELECT COUNT(*) FROM pit_replay WHERE COALESCE(leakage_status,'UNKNOWN') NOT IN ('PASS','CLEAN')"
        ).fetchone()[0])
        if pit_bad:
            report["status"] = "BLOCKED_PIT"
            report["pit_gate"] = {"required": True, "status": "BLOCKED", "bad_rows": pit_bad}
            return _safe(report)

        for sport in active:
            rows, features = base.build(con, sport)
            event_meta = _load_event_metadata(con, sport)
            groups = {}
            for eid, t, label, feats in rows:
                meta = event_meta.get(str(eid), {})
                if not meta.get("competition_id"):
                    continue
                profile = resolve_research_profile(sport, meta.get("competition_id"))
                if not profile.get("matched"):
                    continue
                profile_id = str(profile["profile_id"])
                segment_candidates = build_segment_candidates(
                    profile,
                    sport=sport,
                    season=meta.get("season"),
                    stage=meta.get("stage"),
                    round_=meta.get("round"),
                    event_type=meta.get("event_type"),
                )
                for segment in segment_candidates:
                    segment_id = str(segment["segment_id"])
                    groups.setdefault(segment_id, []).append({
                        "event_id": str(eid),
                        "time": str(t),
                        "label": int(label),
                        "features": feats,
                        "season": meta.get("season") or str(t)[:4],
                        "competition_id": meta.get("competition_id"),
                        "canonical_competition_id": profile.get("canonical_competition_id"),
                        "profile_id": profile_id,
                        "segment_id": segment_id,
                        "segment_specificity": int(segment.get("specificity", 0)),
                        "segment_context": dict(segment.get("context") or {}),
                        "sport": sport,
                    })
            report["blocked"].setdefault(sport, {})
            for segment_id, items in sorted(groups.items()):
                result = _fit_oos(
                    items,
                    features,
                    policy["candidates"],
                    policy["minimums"],
                    symmetric=sport in ("ufc", "rizin"),
                )
                if result.get("status") == "ACCEPTED_LOCKED_HOLDOUT":
                    report["routes"][segment_id] = result
                else:
                    report["blocked"][sport][segment_id] = result
        if report["routes"]:
            report["status"] = "READY"
        else:
            report["status"] = "READY_NO_ACCEPTED_ROUTES"
        return _safe(report)
    finally:
        con.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build competition-specific production routes from PIT-safe chronological OOS plus frozen holdout.")
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--sport", action="append", choices=["basketball", "volleyball", "ufc", "rizin", "valorant"])
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    report = build_route_registry(Path(args.db), args.sport)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
