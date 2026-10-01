from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import src.upset_uncertainty_oos as uq


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
THRESHOLDS = (0.45, 0.50, 0.55, 0.60, 0.65, 0.70)


def evaluate_sport(sport: str) -> dict:
    if not DB.is_file():
        raise SystemExit(f"FAIL_CLOSED_DB_MISSING:{DB}")

    original_threshold = uq.RISK_THRESHOLD
    runs = []

    try:
        for threshold in THRESHOLDS:
            uq.RISK_THRESHOLD = float(threshold)
            with sqlite3.connect(DB) as con:
                result = uq._evaluate_sport(con, sport)
            result["sweep_risk_threshold"] = float(threshold)
            runs.append(result)
    finally:
        uq.RISK_THRESHOLD = original_threshold

    evaluated = [r for r in runs if r.get("status") == "EVALUATED"]

    def selection_summary(result):
        values = []
        for policy in (result.get("policy_grid") or {}).values():
            if not isinstance(policy, dict):
                continue
            blocks = [
                float(b.get("logloss_improvement", float("nan")))
                for b in (policy.get("block_results") or [])
                if isinstance(b, dict)
            ]
            blocks = [v for v in blocks if np.isfinite(v)]
            if not blocks:
                continue
            brier_blocks = [
                float(b.get("brier_improvement", float("nan")))
                for b in (policy.get("block_results") or [])
                if isinstance(b, dict)
            ]
            brier_blocks = [v for v in brier_blocks if np.isfinite(v)]
            values.append({
                "policy": policy,
                "mean_block_logloss_improvement": float(np.mean(blocks)),
                "min_block_logloss_improvement": float(np.min(blocks)),
                "positive_block_count": int(sum(v > 0.0 for v in blocks)),
                "mean_block_brier_improvement": float(np.mean(brier_blocks))
                if brier_blocks else float("nan"),
            })
        if not values:
            return None
        ranked = sorted(
            values,
            key=lambda x: (
                -x["mean_block_logloss_improvement"],
                -x["min_block_logloss_improvement"],
                -x["positive_block_count"],
                -float(x["policy"].get("oos_logloss_improvement", float("-inf"))),
            ),
        )
        return ranked[0]

    ranked = []
    for result in evaluated:
        summary = selection_summary(result)
        if summary is None:
            continue
        policy = summary["policy"]
        evidence_ok = (
            summary["mean_block_logloss_improvement"] > 0.0
            and summary["min_block_logloss_improvement"] > -0.005
            and summary["positive_block_count"] >= 2
            and (
                not np.isfinite(summary["mean_block_brier_improvement"])
                or summary["mean_block_brier_improvement"] >= -0.001
            )
        )
        result["_selection_summary"] = summary
        result["_selection_evidence_ok"] = evidence_ok
        ranked.append(result)

    ranked = sorted(
        ranked,
        key=lambda r: (
            not bool(r.get("_selection_evidence_ok")),
            -float(r["_selection_summary"]["mean_block_logloss_improvement"]),
            -float(r["_selection_summary"]["min_block_logloss_improvement"]),
            -int(r["_selection_summary"]["positive_block_count"]),
        ),
    )

    return {
        "sport": sport,
        "status": "EVALUATED" if evaluated else "DEFERRED",
        "thresholds": list(THRESHOLDS),
        "runs": runs,
        "selection_rule": (
            "pre-holdout OOS only: mean block logloss improvement, "
            "minimum block improvement, >=2 positive blocks; no holdout selection"
        ),
        "best_research_candidate": (
            {
                "sweep_risk_threshold": ranked[0]["sweep_risk_threshold"],
                "selected_policy": ranked[0].get("selected_policy"),
                "selected_strength": ranked[0].get("selected_strength"),
                "pre_holdout_selection_summary": ranked[0].get("_selection_summary"),
                "selection_evidence_ok": bool(ranked[0].get("_selection_evidence_ok")),
            }
            if ranked
            else None
        ),
        "production_model_changed": False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=uq.ACTIVE_SPORTS, required=True)
    ap.add_argument(
        "--output",
        default=None,
        help="Output JSON path. Defaults to results/upset_threshold_sweep_<sport>.json",
    )
    args = ap.parse_args()

    out = Path(args.output) if args.output else ROOT / "results" / f"upset_threshold_sweep_{args.sport}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "RESEARCH_ONLY",
        "method": "chronological OOS threshold sweep; frozen holdout score-only inside each run",
        "sports": [evaluate_sport(args.sport)],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
