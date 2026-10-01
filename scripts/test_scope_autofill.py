#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from src.scope_autofill_controller import ACTIONS, MIN_EVENTS, MIN_VERIFIED, MIN_EXACT_PIT_RATIO, route_score, select_action

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    assert set(ACTIONS) == {
        "basketball", "volleyball", "ufc", "rizin", "valorant",
        "tennis", "f1", "rugby", "boxing",
    }
    for sport, actions in ACTIONS.items():
        assert actions
        for name, command, timeout in actions:
            assert name and isinstance(command, list) and command[0].endswith("python")
            assert timeout > 0
            joined = " ".join(command).lower()
            assert all(x not in joined for x in ("sportsdataio", "the-odds-api", "lsports", "sportradar"))
    assert MIN_EVENTS == 120
    assert MIN_VERIFIED == 80
    assert MIN_EXACT_PIT_RATIO == 0.95
    controller = (ROOT / "src/scope_autofill_controller.py").read_text(encoding="utf-8")
    assert '"rugby": ROOT / "data/db/rugby_v45.sqlite"' in controller
    assert '"boxing": ROOT / "data/db/boxing_v45.sqlite"' in controller
    assert 'tennis_v45.sqlite' not in controller
    assert 'f1_v45.sqlite' not in controller
    assert '--skip-discovery' in controller
    assert 'def competition_frontier' in controller
    discovery = (ROOT / "src/scope_source_discovery.py").read_text(encoding="utf-8")
    assert "GITHUB_TOKEN" in discovery
    assert "discovery_does_not_adopt" in discovery
    assert "retrieval_is_not_historical_pit" in discovery
    assert "def _github_code_leads" in discovery
    assert "code_leads = _github_code_leads()" in discovery
    assert "per_sport = {" in discovery
    assert "DISCOVERY_SIGNAL_TERMS" in discovery
    assert "_discovery_signal_strength" in discovery
    assert '"signal_strength"' in discovery
    assert "code_low_signal_leads" in discovery
    assert "github_code_low_signal_ratio" in discovery
    assert "low_signal_discovery_is_quarantined_not_deleted" in discovery
    assert 'return 0 if status != "FAILED" else 2' in discovery
    assert 'selection_action' in controller

    history = {
        "historical_b_league": {
            "runs": 1, "success": 1, "fail": 0,
            "event_delta": [0], "verified_delta": [0], "pit_delta": [0],
        }
    }
    assert route_score(history, "historical_b_league") == 0.0
    assert route_score(history, "incremental_official") > route_score(history, "historical_b_league")
    assert route_score({}, "incremental_official") > 0.0

    selected = select_action(
        "basketball",
        {"events": 0, "verified_outcomes": 0, "exact_pit_ratio": 0.0},
        set(),
    )
    assert selected and selected[0] == "historical_b_league"

    selected = select_action(
        "basketball",
        {"events": 120, "verified_outcomes": 80, "exact_pit_ratio": 0.50},
        set(),
    )
    assert selected and selected[0] == "strict_pit_replay"

    print("SCOPE_AUTOFILL=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
