from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from src import research_cycle_v4 as base
from src.competition_profiles import profile_policy, resolve_profile

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
OUT = ROOT / "results/research/competition_profiles.json"


def _safe(v):
    if isinstance(v, (np.floating, float)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, dict):
        return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe(x) for x in v]
    return v


def _evaluate_group(items: list[dict], feature_names: list[str], candidates: list[str], minimums: dict) -> dict:
    items = sorted(items, key=lambda x: (x["time"], x["event_id"]))
    n = len(items)
    seasons = sorted({str(x["season"]) for x in items if x.get("season")})
    train_min = int(minimums.get("train_rows", 80))
    folds_target = int(minimums.get("folds", 4))
    min_test = int(minimums.get("test_rows_per_fold", 15))
    if n < int(minimums.get("rows", 120)) or n < train_min + folds_target * min_test or len(set(x["label"] for x in items)) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "rows": n,
            "seasons": seasons,
            "required_rows": int(minimums.get("rows", 120)),
            "required_periods": int(minimums.get("periods", 2)),
        }

    X = np.asarray([[x["features"].get(f, np.nan) for f in feature_names] for x in items], dtype=float)
    y = np.asarray([int(x["label"]) for x in items], dtype=int)
    eval_idx = np.arange(train_min, n)
    blocks = [b for b in np.array_split(eval_idx, folds_target) if len(b) >= min_test]
    if len(blocks) < 4:
        return {"status": "INSUFFICIENT_FOLDS", "rows": n, "seasons": seasons, "folds": len(blocks)}

    available = set(base.pool(feature_names).keys())
    names = [x for x in candidates if x in available]
    if not names:
        return {"status": "NO_AVAILABLE_CANDIDATES", "rows": n, "seasons": seasons}

    results = {}
    for name in names:
        folds = []
        for block in blocks:
            start, end = int(block[0]), int(block[-1]) + 1
            if len(np.unique(y[:start])) < 2 or len(np.unique(y[start:end])) < 2:
                continue
            model = base.pool(feature_names)[name]
            model.fit(X[:start], y[:start])
            p = np.clip(model.predict_proba(X[start:end])[:, 1], 1e-6, 1 - 1e-6)
            m = base.metric(y[start:end], p)
            m["oos_start"] = items[start]["time"]
            m["oos_end"] = items[end - 1]["time"]
            m["not_worse_vs_logistic"] = None
            folds.append(m)
        if len(folds) >= 4:
            agg = {
                "logloss": float(np.mean([x["logloss"] for x in folds])),
                "brier": float(np.mean([x["brier"] for x in folds])),
                "ece": float(np.mean([x["ece"] for x in folds])),
                "accuracy": float(np.mean([x["accuracy"] for x in folds])),
                "folds": len(folds),
                "fold_logloss_std": float(np.std([x["logloss"] for x in folds])),
                "fold_brier_std": float(np.std([x["brier"] for x in folds])),
                "folds_detail": folds,
            }
            results[name] = agg

    if "logistic" not in results or not results:
        return {"status": "INSUFFICIENT_VALID_CANDIDATES", "rows": n, "seasons": seasons, "candidate_results": results}

    baseline = results["logistic"]
    best = min(results, key=lambda k: (results[k]["logloss"], results[k]["brier"], results[k]["ece"]))
    cand = results[best]
    fold_pairs = []
    logistic_folds = {
        (str(x.get("oos_start")), str(x.get("oos_end"))): x
        for x in baseline["folds_detail"]
    }
    best_folds = {
        (str(x.get("oos_start")), str(x.get("oos_end"))): x
        for x in cand["folds_detail"]
    }
    for key, lf in logistic_folds.items():
        bf = best_folds.get(key)
        if bf is not None:
            fold_pairs.append(float(bf["logloss"] <= lf["logloss"] + 1e-12))
    non_worse = float(np.mean(fold_pairs)) if fold_pairs else 0.0
    rel_improvement = float((baseline["logloss"] - cand["logloss"]) / max(abs(baseline["logloss"]), 1e-12))
    periods = seasons if seasons else sorted({x["time"][:4] for x in items if x.get("time")})
    status = "EVALUATED"
    if (
        best != "logistic"
        and len(periods) >= int(minimums.get("periods", 2))
        and rel_improvement >= float(profile_policy()["selection"]["min_relative_logloss_improvement"])
        and non_worse >= float(profile_policy()["selection"]["min_folds_not_worse"])
        and cand["brier"] <= baseline["brier"]
        and cand["ece"] <= baseline["ece"]
    ):
        status = "PROMOTION_CANDIDATE_HOLDOUT_REQUIRED"

    return {
        "status": status,
        "rows": n,
        "periods": periods,
        "seasons": seasons,
        "feature_count": len(feature_names),
        "candidates": results,
        "baseline_model": "logistic",
        "selected_research_candidate": best,
        "baseline_logloss": baseline["logloss"],
        "candidate_logloss": cand["logloss"],
        "relative_logloss_improvement": rel_improvement,
        "fold_non_worse_rate": non_worse,
        "production_route_enabled": False,
        "holdout_required": True,
        "policy": "competition-specific OOS selection is research-only; sport-level production model remains incumbent until independent frozen holdout and release gates pass",
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=["valorant", "basketball", "volleyball", "ufc", "rizin"], default=None)
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    policy = profile_policy()
    active_sports = []
    scope_path = ROOT / "config/ACTIVE_SCOPE_9_SPORTS.json"
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    for sport, entries in (scope.get("active_scope") or {}).items():
        if any(isinstance(e, dict) and str(e.get("status", "")).upper() == "TARGET" for e in entries):
            active_sports.append(sport)
    if args.sport:
        active_sports = [args.sport]

    db_path = Path(args.db).resolve()
    con = sqlite3.connect(db_path)
    try:
        report = {
            "version": "competition-aware-research-v1",
            "status": "EVALUATED",
            "production_route_enabled": False,
            "policy": policy,
            "sports": {},
            "identity_audit": {},
        }
        for sport in active_sports:
            rows, feature_names = base.build(con, sport)
            event_meta = {
                str(eid): {
                    "event_id": str(eid),
                    "name": str(name or ""),
                    "competition_id": str(comp or ""),
                    "season": str(season or ""),
                    "stage": str(stage or ""),
                    "time": str(t or ""),
                }
                for eid, name, comp, season, stage, t in con.execute(
                    "SELECT event_id,name,competition_id,season,stage,event_time_utc FROM event WHERE sport=?",
                    (sport,),
                ).fetchall()
            }
            grouped = {}
            identity = {"built_rows": len(rows), "matched_rows": 0, "unknown_competition_rows": 0, "missing_competition_rows": 0}
            for eid, t, label, feats in rows:
                meta = event_meta.get(str(eid), {})
                profile = resolve_profile(sport, meta.get("competition_id"), meta.get("name"))
                if profile["matched"]:
                    identity["matched_rows"] += 1
                    key = profile["profile_id"]
                    grouped.setdefault(key, {
                        "profile": profile,
                        "items": [],
                    })["items"].append({
                        "event_id": str(eid), "time": str(t), "label": int(label), "features": feats,
                        "season": meta.get("season") or str(t)[:4],
                    })
                else:
                    if meta.get("competition_id"):
                        identity["unknown_competition_rows"] += 1
                    else:
                        identity["missing_competition_rows"] += 1
            report["identity_audit"][sport] = {
                **identity,
                "recognized_ratio": (identity["matched_rows"] / max(identity["built_rows"], 1)),
            }
            sport_profiles = {}
            for profile_id, payload in grouped.items():
                profile = payload["profile"]
                sport_profiles[profile_id] = {
                    "profile": profile,
                    "evaluation": _evaluate_group(
                        payload["items"],
                        feature_names,
                        ["logistic", "extra_trees", "hist_gb", "hist_gb_shallow", "lightgbm", "lightgbm_missing"],
                        policy["minimums"],
                    ),
                }
            report["sports"][sport] = sport_profiles

        output_path = Path(args.out) if args.out else (
            ROOT / "results/research" / (
                f"competition_profiles_{args.sport}.json" if args.sport else "competition_profiles.json"
            )
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(_safe(report), ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        print(json.dumps(_safe(report), ensure_ascii=False, indent=2, allow_nan=False))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
