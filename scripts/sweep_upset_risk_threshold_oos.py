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
    ranked = sorted(
        evaluated,
        key=lambda r: (
            -max(
                float(v.get("oos_logloss_improvement", float("-inf")))
                for v in (r.get("policy_grid") or {}).values()
                if isinstance(v, dict)
            ),
            float(r.get("holdout", {}).get("ece_change", float("inf"))),
        ),
    )

    return {
        "sport": sport,
        "status": "EVALUATED" if evaluated else "DEFERRED",
        "thresholds": list(THRESHOLDS),
        "runs": runs,
        "best_research_candidate": (
            {
                "sweep_risk_threshold": ranked[0]["sweep_risk_threshold"],
                "selected_policy": ranked[0].get("selected_policy"),
                "selected_strength": ranked[0].get("selected_strength"),
                "holdout": ranked[0].get("holdout"),
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
