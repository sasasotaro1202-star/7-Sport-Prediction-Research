from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "config" / "SPORT_DATA_SOURCES_9.json"
OUT = ROOT / "results" / "cross_sport_source_probe" / "coverage_audit.json"


def main() -> int:
    cfg = json.loads(SOURCES.read_text(encoding="utf-8"))
    sports = cfg["sports"]
    report = {
        "version": "cross-sport-coverage-audit-v1",
        "research_only": True,
        "production_model_touched": False,
        "sports_count": len(sports),
        "sports": {},
    }

    for sport, rows in sorted(sports.items()):
        data_rows = [
            row for row in rows
            if row.get("class") not in {"market_source", "discovery_aggregator"}
        ]
        secondary = [row for row in rows if row.get("class") == "secondary"]
        integrated = [row for row in rows if row.get("integrated") is True]
        report["sports"][sport] = {
            "source_count": len(rows),
            "free_source_count": sum(bool(row.get("free")) for row in rows),
            "independent_data_source_count": len(data_rows),
            "secondary_count": len(secondary),
            "research_only_count": sum(row.get("class") == "research_only" for row in rows),
            "integrated_count": len(integrated),
            "pit_unverified_candidate_count": sum(
                row.get("pit") not in {"replay_required", "github_provenance"}
                for row in rows
                if row.get("integrated") is not True
            ),
            "needs_source_expansion": len(data_rows) < 2,
        }

    assert set(report["sports"]) == {
        "basketball", "volleyball", "ufc", "rizin", "valorant",
        "tennis", "f1", "rugby", "boxing",
    }
    assert all(
        row["independent_data_source_count"] >= 2
        for row in report["sports"].values()
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CROSS_SPORT_COVERAGE_AUDIT=PASS")
    for sport, row in report["sports"].items():
        print(
            f"{sport.upper()}: sources={row['source_count']} "
            f"independent={row['independent_data_source_count']} "
            f"secondary={row['secondary_count']} "
            f"integrated={row['integrated_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
