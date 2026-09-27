#!/usr/bin/env python3
"""Fail-closed audit for nine-sport source coverage and source-family diversity.

Research metadata only: this does not fetch providers and cannot promote any source.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "SPORT_DATA_SOURCES_9.json"
EXPECTED_SPORTS = {
    "basketball", "volleyball", "ufc", "rizin", "valorant",
    "tennis", "f1", "rugby", "boxing",
}


def load() -> dict[str, Any]:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert data["policy"]["free_only"] is True
    assert data["policy"]["production_default_requires_pit"] is True
    assert data["policy"]["unknown_availability_is_fail_closed"] is True
    assert data["independence_policy"]["minimum_distinct_families_for_redundancy"] >= 2
    return data


def audit(data: dict[str, Any]) -> list[dict[str, Any]]:
    sports = data.get("sports", {})
    if set(sports) != EXPECTED_SPORTS:
        missing = sorted(EXPECTED_SPORTS - set(sports))
        extra = sorted(set(sports) - EXPECTED_SPORTS)
        raise AssertionError(f"sport_scope_mismatch missing={missing} extra={extra}")

    report: list[dict[str, Any]] = []
    for sport in sorted(EXPECTED_SPORTS):
        rows = sports[sport]
        ids = [x.get("id") for x in rows]
        if len(ids) != len(set(ids)):
            raise AssertionError(f"duplicate_source_id sport={sport}")
        for x in rows:
            assert x.get("free") is True, (sport, x)
            assert x.get("integrated") in (True, False), (sport, x)
            assert x.get("pit") not in (None, ""), (sport, x)
            assert x.get("independence_family") not in (None, "", "unknown_family"), (sport, x)

        integrated = [
            x for x in rows
            if x["integrated"] and x["class"] not in {"market_source", "discovery_aggregator"}
        ]
        statistical_rows = [
            x for x in rows
            if x["class"] not in {"market_source", "discovery_aggregator"}
        ]
        families = sorted({x["independence_family"] for x in statistical_rows})
        if not integrated:
            raise AssertionError(f"no_integrated_statistical_primary sport={sport}")
        if len(families) < 2:
            raise AssertionError(f"insufficient_statistical_source_family_diversity sport={sport}")

        report.append({
            "sport": sport,
            "source_count": len(rows),
            "integrated_count": len(integrated),
            "distinct_source_families": len(families),
            "sources": ids,
            "status": "PASS",
        })
    return report


def main() -> int:
    data = load()
    report = audit(data)
    print("CROSS_SPORT_COVERAGE_AUDIT=PASS")
    for row in report:
        print(
            f"{row['sport'].upper()} "
            f"sources={row['source_count']} "
            f"integrated={row['integrated_count']} "
            f"families={row['distinct_source_families']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
