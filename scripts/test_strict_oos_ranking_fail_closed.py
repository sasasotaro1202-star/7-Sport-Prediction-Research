from __future__ import annotations

import json

from src.research_cycle_strict import _rank_valid_oos_candidates


def test_malformed_candidate_is_rejected_without_typeerror():
    ranked, invalid = _rank_valid_oos_candidates({
        "good": {"robust_objective": 0.68, "brier": 0.24, "ece": 0.03, "logloss": 0.68},
        "broken": "TRAIN_FAILED",
        "nan_metric": {"robust_objective": float("nan"), "brier": 0.24, "ece": 0.03, "logloss": 0.68},
    })
    assert ranked == ["good"]
    assert invalid["broken"]["reason"] == "oos_score_not_object"
    assert invalid["nan_metric"]["reason"] == "oos_score_invalid_metrics"
    json.dumps(invalid, ensure_ascii=False)


def test_no_valid_candidates_is_fail_closed():
    ranked, invalid = _rank_valid_oos_candidates({
        "broken_a": "TRAIN_FAILED",
        "broken_b": {"robust_objective": 0.6, "brier": 0.2, "ece": 0.02},
    })
    assert ranked == []
    assert set(invalid) == {"broken_a", "broken_b"}
