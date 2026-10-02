from __future__ import annotations

from src.dual_learning_cycle import _command
from src.research_cycle_strict import _rank_oos_candidates


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


def test_oos_ranker_rejects_window_metadata_mixed_into_candidates():
    scores = {
        "m1": {"robust_objective": 0.70, "brier": 0.24, "ece": 0.02},
        "m2": {"robust_objective": 0.68, "brier": 0.245, "ece": 0.03},
    }
    assert _rank_oos_candidates(scores) == ["m2", "m1"]
    mixed = dict(scores)
    mixed["window_signature"] = "9f8f9c"
    try:
        _rank_oos_candidates(mixed)
    except RuntimeError as exc:
        assert str(exc) == "invalid_oos_candidate_entries:window_signature"
    else:
        raise AssertionError("OOS metadata contamination must fail closed")
