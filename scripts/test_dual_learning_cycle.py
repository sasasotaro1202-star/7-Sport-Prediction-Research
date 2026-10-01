from __future__ import annotations

from src.dual_learning_cycle import _command


def test_experience_lane_is_independent():
    cmd = _command("experience", "volleyball")
    assert cmd[cmd.index("-m") + 1] == "src.experience_learning"
    assert "--sport" not in cmd


def test_historical_lane_uses_chronological_research():
    cmd = _command("research", "volleyball")
    assert cmd[cmd.index("-m") + 1] == "src.research_cycle_strict"
    assert cmd[-2:] == ["--sport", "volleyball"]


def test_lanes_are_distinct():
    assert _command("experience", "volleyball") != _command("research", "volleyball")


if __name__ == "__main__":
    test_experience_lane_is_independent()
    test_historical_lane_uses_chronological_research()
    test_lanes_are_distinct()
    print("dual_learning_cycle tests passed")
