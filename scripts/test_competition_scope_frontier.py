from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "COMPETITION_SCOPE_FRONTIER.json"


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert cfg["policy"]["free_only"] is True
    assert cfg["policy"]["research_only"] is True
    assert cfg["policy"]["production_model_changes"] is False

    excluded = set(cfg["policy"]["excluded_sports_never_discover"])
    assert excluded == {"baseball", "soccer"}
    assert not excluded.intersection(cfg["target_sports"])

    expected = {
        "basketball": {"domestic_league", "domestic_cup", "continental_club", "qualifier", "friendly"},
        "volleyball": {"domestic_league", "domestic_cup", "continental_club", "qualifier", "friendly"},
        "ufc": {"numbered_event", "fight_night_event", "special_event", "tournament_or_series"},
        "rizin": {"numbered_event", "grand_prix", "title_event", "special_event"},
        "valorant": {"regional_league", "regional_cup", "international_event", "masters", "champions", "challengers", "game_changers", "qualifier"},
    }
    for sport, required in expected.items():
        values = set(cfg["competition_frontier"][sport])
        assert required <= values
        assert len(values) == len(cfg["competition_frontier"][sport])

    assert cfg["promotion_stages"][0] == "DISCOVERED"
    assert "PIT_VALIDATED" in cfg["promotion_stages"]
    assert "historical_pit_unproven" in cfg["stop_conditions"]
    required_metadata = set(cfg["minimum_metadata"])
    assert {"sport", "competition_id", "competition_type", "event_id", "event_time_utc", "source_available_at_utc", "pit_status"} <= required_metadata

    print("COMPETITION_SCOPE_CONFIG=PASS")
    print("COMPETITION_SCOPE_EXCLUSIONS=PASS")
    print("COMPETITION_SCOPE_TYPES=PASS")
    print("COMPETITION_SCOPE_PIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
