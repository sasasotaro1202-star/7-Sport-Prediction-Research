from __future__ import annotations

from src.experience_research_bridge import build


def _memory(recommendation="EXPERIENCE_REVIEW"):
    return {
        "version": "experience-learning-v1",
        "pit_status": "PASS",
        "knowledge_available_at_utc": "2026-10-01T10:00:00+00:00",
        "source": {"source_settled_through_utc": "2026-10-01T09:00:00+00:00"},
        "memory": [{
            "memory_key": "basketball|basketball:bleague_men|fixed_equal_weight|0.80-0.90|30",
            "recommendation": recommendation,
            "knowledge_available_at_utc": "2026-10-01T10:00:00+00:00",
            "source_settled_through_utc": "2026-10-01T09:00:00+00:00",
            "sport": "basketball",
            "competition_profile_id": "basketball:bleague_men",
            "strategy": "fixed_equal_weight",
            "probability_bucket": "0.80-0.90",
            "target_lead_minutes": "30",
            "n": 20,
            "accuracy": 0.30,
            "accuracy_wilson_lower_bound": 0.13,
            "high_confidence_n": 20,
            "high_confidence_accuracy": 0.30,
            "reason": "historical_accuracy_lower_bound_below_threshold",
        }]
    }


def test_review_row_creates_prospective_candidate():
    out = build(_memory(), "2026-10-01T11:00:00+00:00")
    assert out["candidate_count"] == 1
    c = out["candidates"][0]
    assert c["validation_mode"] == "PROSPECTIVE_ONLY"
    assert c["historical_oos_reuse_allowed"] is False
    assert c["promotion_allowed"] is False
    assert c["pit_status"] == "PASS"


def test_healthy_row_creates_no_candidate():
    out = build(_memory("PASS"), "2026-10-01T11:00:00+00:00")
    assert out["candidate_count"] == 0


def test_future_knowledge_time_fails_closed():
    try:
        build(_memory(), "2026-10-01T09:59:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "EXPERIENCE_BRIDGE_KNOWLEDGE_TIME_IN_FUTURE"
    else:
        raise AssertionError("expected fail-closed knowledge-time error")


def test_inconsistent_source_settlement_time_fails_closed():
    memory = _memory()
    memory["source"]["source_settled_through_utc"] = "2026-10-01T10:00:01+00:00"
    try:
        build(memory, "2026-10-01T11:00:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "EXPERIENCE_BRIDGE_SOURCE_SETTLEMENT_TIME_INCONSISTENT"
    else:
        raise AssertionError("expected fail-closed source settlement-time error")


def test_row_missing_source_settlement_time_fails_closed():
    memory = _memory()
    memory["memory"][0].pop("source_settled_through_utc")
    try:
        build(memory, "2026-10-01T11:00:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "EXPERIENCE_BRIDGE_ROW_MISSING_SOURCE_SETTLEMENT_TIME"
    else:
        raise AssertionError("expected fail-closed row provenance error")


if __name__ == "__main__":
    test_review_row_creates_prospective_candidate()
    test_healthy_row_creates_no_candidate()
    test_future_knowledge_time_fails_closed()
    test_inconsistent_source_settlement_time_fails_closed()
    test_row_missing_source_settlement_time_fails_closed()
    print("experience_research_bridge tests passed")
