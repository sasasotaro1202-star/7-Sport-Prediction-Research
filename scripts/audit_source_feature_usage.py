#!/usr/bin/env python3
"""Audit configured sources against actual PIT-safe research feature usage.

This is research metadata only. It never writes models or production state.
The key distinction is:
  registry candidate -> observed in DB -> exact PIT rows -> feature matrix usage.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from src import research_cycle_v4 as base

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "SPORT_DATA_SOURCES_9.json"
DB = ROOT / "data" / "db" / "sports_v45.sqlite"
RESULTS = ROOT / "results" / "research"
SHADOW = ROOT / "results" / "cross_sport_shadow" / "shadow_sources.json"


def load_registry() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _count(con: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    row = con.execute(sql, params).fetchone()
    return int(row[0] or 0)


def _exact_snapshot_stats(con: sqlite3.Connection, sport: str, policy: tuple[str, ...]) -> dict[str, int]:
    if not policy:
        return {"exact_snapshot_count": 0, "exact_pit_stat_rows": 0}
    q = ",".join("?" * len(policy))
    exact_snapshots = _count(
        con,
        """
        SELECT COUNT(DISTINCT ss.snapshot_id)
          FROM source_snapshot ss
         WHERE ss.sport=?
           AND ss.availability_status='EXACT'
           AND ss.source_available_at_utc IS NOT NULL
        """,
        (sport,),
    )
    exact_pit_rows = _count(
        con,
        f"""
        SELECT COUNT(*)
          FROM match_stats ms
          JOIN event e ON e.event_id=ms.event_id
          JOIN source_snapshot ss
            ON ss.source=ms.source
           AND COALESCE(ss.source_url,'')=COALESCE(ms.source_url,'')
           AND ss.availability_status='EXACT'
           AND ss.source_available_at_utc IS NOT NULL
           AND (ss.event_time_utc IS NULL OR ss.event_time_utc=e.event_time_utc)
         WHERE ms.sport=?
           AND ms.stat_name IN ({q})
           AND ms.value_num IS NOT NULL
           AND ms.effective_at_utc IS NOT NULL
           AND datetime(ms.effective_at_utc) <= datetime(e.event_time_utc, '-60 minutes')
           AND datetime(ss.source_available_at_utc) <= datetime(e.event_time_utc, '-60 minutes')
        """,
        (sport, *policy),
    )
    return {
        "exact_snapshot_count": exact_snapshots,
        "exact_pit_stat_rows": exact_pit_rows,
    }


def _source_usage(con: sqlite3.Connection, sport: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT source,
               SUM(CASE WHEN table_name='event_participant' THEN 1 ELSE 0 END) AS participant_rows,
               SUM(CASE WHEN table_name='match_stats' THEN 1 ELSE 0 END) AS stat_rows,
               SUM(CASE WHEN table_name='source_snapshot' THEN 1 ELSE 0 END) AS snapshot_rows,
               SUM(CASE WHEN table_name='source_snapshot' AND availability_status='EXACT' THEN 1 ELSE 0 END) AS exact_snapshots
          FROM (
            SELECT ep.source AS source,
                   'event_participant' AS table_name,
                   NULL AS availability_status
              FROM event_participant ep
              JOIN event e ON e.event_id=ep.event_id
             WHERE e.sport=? AND ep.source IS NOT NULL
            UNION ALL
            SELECT ms.source AS source,
                   'match_stats' AS table_name,
                   NULL AS availability_status
              FROM match_stats ms
             WHERE ms.sport=? AND ms.source IS NOT NULL
            UNION ALL
            SELECT ss.source AS source,
                   'source_snapshot' AS table_name,
                   ss.availability_status AS availability_status
              FROM source_snapshot ss
             WHERE ss.sport=? AND ss.source IS NOT NULL
          )
         GROUP BY source
         ORDER BY source
        """,
        (sport, sport, sport),
    ).fetchall()
    return [
        {
            "source": str(r[0]),
            "event_participant_rows": int(r[1] or 0),
            "match_stat_rows": int(r[2] or 0),
            "snapshot_rows": int(r[3] or 0),
            "exact_snapshot_rows": int(r[4] or 0),
        }
        for r in rows
    ]


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _feature_usage(rows: list[tuple[Any, Any, Any, dict[str, Any]]], policy: tuple[str, ...]) -> dict[str, Any]:
    feature_names = sorted({name for *_, features in rows for name in features})
    stat_usage: dict[str, Any] = {}
    for stat in policy:
        cols = [name for name in feature_names if f"__{stat}__" in name]
        finite_counts = {
            name: sum(1 for *_, features in rows if _finite(features.get(name)))
            for name in cols
        }
        stat_usage[stat] = {
            "feature_columns": cols,
            "finite_row_counts": finite_counts,
            "active_in_feature_matrix": any(count > 0 for count in finite_counts.values()),
        }
    active_stats = [s for s, v in stat_usage.items() if v["active_in_feature_matrix"]]
    return {
        "feature_count": len(feature_names),
        "active_policy_stats": active_stats,
        "active_policy_stat_count": len(active_stats),
        "stat_feature_usage": stat_usage,
    }


def _shadow_usage(sport: str) -> dict[str, Any]:
    if not SHADOW.exists():
        return {"status": "NOT_CAPTURED_IN_CURRENT_WORKTREE", "sources": []}
    try:
        payload = json.loads(SHADOW.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "INVALID_SHADOW_ARTIFACT", "error": type(exc).__name__, "sources": []}
    rows = [
        row for row in payload.get("sources", [])
        if row.get("sport") == sport and row.get("status") == "PASS"
    ]
    return {
        "status": "CAPTURED" if rows else "NO_HEALTHY_CURRENT_CAPTURE",
        "sources": [row.get("source") for row in rows],
        "historical_pit_status": payload.get("historical_pit_status"),
    }


def audit_sport(
    con: sqlite3.Connection,
    sport: str,
    registry: dict[str, Any],
) -> dict[str, Any]:
    policy = tuple(base.POLICY.get(sport, ()))
    configured = list((registry.get("sports") or {}).get(sport, []))
    integrated = [
        row for row in configured
        if row.get("integrated") is True
        and row.get("class") not in {"market_source", "discovery_aggregator"}
    ]
    observed_stats = sorted(
        str(row[0]) for row in con.execute(
            "SELECT DISTINCT stat_name FROM match_stats WHERE sport=? AND stat_name IS NOT NULL",
            (sport,),
        ).fetchall()
    )
    policy_observed = sorted(set(policy) & set(observed_stats))
    pit = _exact_snapshot_stats(con, sport, policy)
    rows, _ = base.build(con, sport)
    usage = _feature_usage(rows, policy)
    source_usage = _source_usage(con, sport)
    event_count = _count(con, "SELECT COUNT(*) FROM event WHERE sport=?", (sport,))
    verified_outcomes = _count(
        con,
        "SELECT COUNT(*) FROM event_outcome WHERE sport=? AND outcome_status='VERIFIED'",
        (sport,),
    )
    integrated_ids = [str(row.get("id")) for row in integrated]
    observed_sources = sorted(row["source"] for row in source_usage)
    exact_used_sources = sorted(
        row["source"] for row in source_usage if row["exact_snapshot_rows"] > 0
    )

    if usage["active_policy_stat_count"] > 0:
        input_status = "DIRECT_STATS_ACTIVE"
    elif rows:
        input_status = "STATE_ONLY"
    else:
        input_status = "NO_PIT_ELIGIBLE_ROWS"

    return {
        "sport": sport,
        "research_only": True,
        "production_model_touched": False,
        "registry": {
            "candidate_count": len(configured),
            "free_candidate_count": sum(bool(x.get("free")) for x in configured),
            "integrated_candidate_ids": integrated_ids,
            "integrated_candidate_count": len(integrated),
        },
        "database": {
            "event_count": event_count,
            "verified_outcome_count": verified_outcomes,
            "observed_stat_names": observed_stats,
            "policy_stat_names": list(policy),
            "policy_stats_observed_in_db": policy_observed,
            "source_names_observed_in_db": observed_sources,
            "source_names_with_exact_snapshots": exact_used_sources,
            **pit,
        },
        "strict_feature_matrix": {
            "build_rows": len(rows),
            **usage,
        },
        "source_usage": source_usage,
        "current_shadow": _shadow_usage(sport),
        "input_status": input_status,
        "interpretation": (
            "direct policy statistics are actually present in the strict feature matrix"
            if input_status == "DIRECT_STATS_ACTIVE"
            else "only derived PIT-safe state features are available"
            if input_status == "STATE_ONLY"
            else "no strict PIT-eligible build rows are available"
        ),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", choices=base.SPORTS, required=True)
    args = parser.parse_args()

    if not DB.exists():
        raise SystemExit(f"database missing: {DB}")

    con = sqlite3.connect(DB)
    try:
        report = audit_sport(con, args.sport, load_registry())
    finally:
        con.close()

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{args.sport}_source_usage.json"
    report["generated_at_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    report["git_sha"] = os.getenv("GITHUB_SHA")
    if not report["git_sha"]:
        try:
            report["git_sha"] = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
        except Exception:
            report["git_sha"] = None
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SOURCE_USAGE_AUDIT={report['sport']} STATUS={report['input_status']}")
    print(
        f"events={report['database']['event_count']} "
        f"verified_outcomes={report['database']['verified_outcome_count']} "
        f"build_rows={report['strict_feature_matrix']['build_rows']} "
        f"exact_pit_stat_rows={report['database']['exact_pit_stat_rows']} "
        f"active_policy_stats={report['strict_feature_matrix']['active_policy_stats']}"
    )
    for row in report["source_usage"]:
        print(
            f"SOURCE={row['source']} "
            f"participant_rows={row['event_participant_rows']} "
            f"stat_rows={row['match_stat_rows']} "
            f"exact_snapshots={row['exact_snapshot_rows']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
