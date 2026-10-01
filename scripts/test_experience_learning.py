from __future__ import annotations

from datetime import datetime, timezone

from src.experience_learning import build_memory, shadow_signal_from_memory


def _row(pid: str, correct: bool, settled: str = "2026-10-01T10:00:00+00:00") -> dict:
    return {
        "prediction_id": pid,
        "settlement_status": "SCORED",
        "prediction_cutoff_at_utc": "2026-10-01T09:00:00+00:00",
        "settled_at_utc": settled,
        "correct": correct,
        "max_probability": 0.85,
        "logloss": 0.9 if not correct else 0.2,
        "brier": 0.72 if not correct else 0.04,
        "sport": "basketball",
        "competition_profile": {"profile_id": "basketball:bleague_men"},
        "strategy": "fixed_equal_weight",
        "probability_bucket": "0.80-0.90",
        "target_lead_minutes": 30,
    }


def test_underperforming_group_becomes_shadow_review():
    rows = [_row(f"p{i}", i < 6) for i in range(20)]
    artifact = build_memory(rows, "2026-10-01T11:00:00+00:00")
    item = artifact["memory"][0]
    assert item["recommendation"] == "EXPERIENCE_REVIEW"
    assert artifact["promotion_gate"] is False
    assert artifact["mode"] == "SHADOW_ONLY"

    signal = shadow_signal_from_memory(
        artifact,
        "2026-10-01T12:00:00+00:00",
        "basketball",
        "basketball:bleague_men",
        "fixed_equal_weight",
        0.85,
        30,
    )
    assert signal["status"] == "SHADOW"
    assert signal["recommendation"] == "EXPERIENCE_REVIEW"
    assert signal["safe_action"] == "PASS"


def test_healthy_group_stays_pass():
    rows = [_row(f"p{i}", i < 17) for i in range(20)]
    artifact = build_memory(rows, "2026-10-01T11:00:00+00:00")
    assert artifact["memory"][0]["recommendation"] == "PASS"


def test_memory_is_pit_gated_by_knowledge_time():
    rows = [_row(f"p{i}", i < 6) for i in range(20)]
    artifact = build_memory(rows, "2026-10-01T11:00:00+00:00")
    signal = shadow_signal_from_memory(
        artifact,
        "2026-10-01T10:59:59+00:00",
        "basketball",
        "basketball:bleague_men",
        "fixed_equal_weight",
        0.85,
        30,
    )
    assert signal["status"] == "PIT_NOT_YET_AVAILABLE"
    assert signal["recommendation"] == "PASS"


def test_invalid_settlement_time_fails_closed():
    row = _row("bad", False)
    row["settled_at_utc"] = "2026-10-01T08:59:00+00:00"
    try:
        build_memory([row], "2026-10-01T11:00:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "EXPERIENCE_LEARNING_PIT_SETTLEMENT_BEFORE_CUTOFF"
    else:
        raise AssertionError("expected fail-closed PIT error")


def test_future_settlement_fails_closed():
    row = _row("future", False)
    row["settled_at_utc"] = "2026-10-01T12:00:00+00:00"
    try:
        build_memory([row], "2026-10-01T11:00:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "EXPERIENCE_LEARNING_FUTURE_SETTLEMENT"
    else:
        raise AssertionError("expected fail-closed future-settlement error")


def test_exact_duplicate_settlement_is_deduplicated():
    row = _row("dup", True)
    artifact = build_memory([row, dict(row)], "2026-10-01T11:00:00+00:00")
    assert artifact["source"]["settlement_rows"] == 1
    assert artifact["memory"][0]["n"] == 1


def test_conflicting_duplicate_settlement_fails_closed():
    row = _row("conflict", True)
    conflicting = dict(row)
    conflicting["correct"] = False
    conflicting["logloss"] = 0.9
    conflicting["brier"] = 0.72
    try:
        build_memory([row, conflicting], "2026-10-01T11:00:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "EXPERIENCE_LEARNING_DUPLICATE_CONFLICT"
    else:
        raise AssertionError("expected fail-closed duplicate conflict error")


def test_missing_prediction_id_fails_closed():
    row = _row("missing-id", True)
    row["prediction_id"] = ""
    try:
        build_memory([row], "2026-10-01T11:00:00+00:00")
    except RuntimeError as exc:
        assert str(exc) == "EXPERIENCE_LEARNING_MISSING_PREDICTION_ID"
    else:
        raise AssertionError("expected fail-closed missing-id error")


if __name__ == "__main__":
    test_underperforming_group_becomes_shadow_review()
    test_healthy_group_stays_pass()
    test_memory_is_pit_gated_by_knowledge_time()
    test_invalid_settlement_time_fails_closed()
    test_future_settlement_fails_closed()
    test_exact_duplicate_settlement_is_deduplicated()
    test_conflicting_duplicate_settlement_fails_closed()
    test_missing_prediction_id_fails_closed()
    print("experience_learning tests passed")
