from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.cross_sport_data_layer import pit_status, source_candidates

SPORTS = (
    "basketball", "volleyball", "ufc", "rizin", "valorant",
    "tennis", "f1", "rugby", "boxing",
)


def main() -> int:
    cfg = json.loads((ROOT / "config/SPORT_DATA_SOURCES_9.json").read_text(encoding="utf-8"))
    assert cfg["policy"]["free_only"] is True
    assert cfg["policy"]["production_default_requires_pit"] is True
    assert cfg["policy"]["unknown_availability_is_fail_closed"] is True
    context = cfg["evidence"]["cross_sport_context"]["sources"]
    for required in ("gdelt", "open_meteo", "openstreetmap_overpass", "wikidata"):
        assert required in context
        assert context[required]["free"] is True
    assert cfg["evidence"]["sportscore"]["status"] == "research_candidate"
    assert cfg["sports"]["basketball"][2]["id"] == "sportscore"
    assert cfg["sports"]["tennis"][2]["id"] == "sportscore"
    assert cfg["evidence"]["discovery_aggregator"]["status"] == "discovery_only"

    for sport in SPORTS:
        rows = source_candidates(sport, research=True, free_only=True)
        assert rows, f"{sport}: no free source candidates"
        assert any(r["integrated"] for r in rows), f"{sport}: no integrated source"
        for row in rows:
            assert row["free"] is True, f"{sport}/{row['id']}: non-free source in free registry"
            assert row["pit"] not in ("pass", "PASS"), (
                f"{sport}/{row['id']}: registry must not pre-approve PIT"
            )

    assert pit_status(
        available_at="2026-01-01T00:00:00Z",
        prediction_time="2026-01-01T00:00:01Z",
    ) == "PASS"
    assert pit_status(
        available_at="2026-01-01T00:00:02Z",
        prediction_time="2026-01-01T00:00:01Z",
    ) == "FAIL"
    assert pit_status(
        available_at=None,
        prediction_time="2026-01-01T00:00:01Z",
    ) == "UNKNOWN_FAIL_CLOSED"
    assert pit_status(
        available_at="not-a-time",
        prediction_time="2026-01-01T00:00:01Z",
    ) == "UNKNOWN_FAIL_CLOSED"

    # Timezone-unknown timestamps must never be silently interpreted as UTC.
    assert pit_status(
        available_at="2026-01-01T00:00:00",
        prediction_time="2026-01-01T00:00:01Z",
    ) == "UNKNOWN_FAIL_CLOSED"
    assert pit_status(
        available_at="2026-01-01T00:00:00Z",
        prediction_time="2026-01-01T00:00:01",
    ) == "UNKNOWN_FAIL_CLOSED"
    assert pit_status(
        available_at=123,  # type: ignore[arg-type]
        prediction_time="2026-01-01T00:00:01Z",
    ) == "UNKNOWN_FAIL_CLOSED"

    print("NINE_SPORT_SOURCE_REGISTRY=PASS")
    print("NINE_SPORT_PIT_ROUTER=PASS")
    print("NINE_SPORT_FREE_ONLY=PASS")
    print("NINE_SPORT_PIT_TIMEZONE_FAIL_CLOSED=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
