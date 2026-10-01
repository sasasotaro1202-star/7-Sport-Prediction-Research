from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from src import research_cycle_v4 as base
from src.upset_uncertainty_oos import _accepted_artifact, DB

ROOT = Path(__file__).resolve().parents[1]


def diagnose(con: sqlite3.Connection, sport: str) -> dict:
    pairs = base.pairmap(con, sport)
    labels, hist = base.outcome_maps(con, sport, pairs)
    stat_names = base.statcols(con, sport)
    rows, features = base.build(con, sport)
    artifact, artifact_reason = _accepted_artifact(sport)

    total_pairs = len(pairs)
    complete_pairs = sum(
        int("A" in p and "B" in p) for p in pairs.values()
    )
    hist_events = len(hist)
    exact_source_rows = con.execute(
        """
        SELECT COUNT(*)
        FROM match_stats ms
        JOIN event e ON e.event_id = ms.event_id
        JOIN source_snapshot ss
          ON ss.source = ms.source
         AND ss.source_url = ms.source_url
         AND ss.availability_status = 'EXACT'
         AND ss.source_available_at_utc IS NOT NULL
         AND (ss.event_time_utc IS NULL OR ss.event_time_utc = e.event_time_utc)
        WHERE ms.sport = ?
          AND ms.value_num IS NOT NULL
          AND ms.effective_at_utc IS NOT NULL
        """,
        (sport,),
    ).fetchone()[0]

    # This is intentionally diagnostic only. It does not relax base.build()
    # and therefore cannot turn an unevaluable dataset into an evaluated one.
    return {
        "sport": sport,
        "status": "DIAGNOSTIC_ONLY",
        "database": str(DB),
        "pair_events": total_pairs,
        "complete_pair_events": complete_pairs,
        "verified_outcome_events": len(labels),
        "historical_outcome_rows": hist_events,
        "eligible_strict_pit_rows_exact_build": len(rows),
        "feature_columns_exact_build": len(features),
        "configured_stat_names": list(stat_names),
        "exact_provenance_match_stats_rows": int(exact_source_rows),
        "accepted_artifact_present": artifact is not None,
        "accepted_artifact_reason": artifact_reason,
        "blocking_interpretation": (
            "base.build() produced no rows; inspect outcome maturity and/or "
            "exact source provenance before relaxing any PIT gate"
            if len(rows) == 0
            else "base.build() produced rows; the upset-risk evaluator may proceed"
        ),
        "production_effect": "none",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    out = Path(args.output) if args.output else ROOT / "results" / f"upset_pit_coverage_{args.sport}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as con:
        payload = diagnose(con, args.sport)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
