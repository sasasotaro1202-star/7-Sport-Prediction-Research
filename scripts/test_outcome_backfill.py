from __future__ import annotations

import sqlite3

from src.outcome_backfill import init, upsert_verified_outcome


def test_verified_outcome_is_immutable() -> None:
    con = sqlite3.connect(":memory:")
    init(con)
    con.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "e1", "basketball", "a", "b", "A", 80, 70, "VERIFIED",
            "old-source", "https://old.invalid", "2026-01-01T00:00:00+00:00",
            "PIT_REQUIRES_REPLAY", "original",
        ),
    )
    con.commit()

    upsert_verified_outcome(
        con,
        event_id="e1",
        sport="basketball",
        side_a_participant_id="a",
        side_b_participant_id="b",
        outcome="B",
        score_a=70,
        score_b=80,
        source="new-source",
        source_url="https://new.invalid",
        observed_at_utc="2026-01-02T00:00:00+00:00",
    )

    row = con.execute(
        "SELECT outcome,score_a,score_b,source,source_url,observed_at_utc,reason "
        "FROM event_outcome WHERE event_id='e1'"
    ).fetchone()
    assert row == (
        "A",
        80.0,
        70.0,
        "old-source",
        "https://old.invalid",
        "2026-01-01T00:00:00+00:00",
        "original",
    )


def test_deferred_outcome_can_be_upgraded_once() -> None:
    con = sqlite3.connect(":memory:")
    init(con)
    con.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "e2", "basketball", "a", "b", None, None, None, "DEFERRED",
            None, None, "2026-01-01T00:00:00+00:00",
            "PIT_REQUIRES_REPLAY", "waiting",
        ),
    )
    con.commit()

    upsert_verified_outcome(
        con,
        event_id="e2",
        sport="basketball",
        side_a_participant_id="a",
        side_b_participant_id="b",
        outcome="A",
        score_a=90,
        score_b=85,
        source="source",
        source_url="https://source.invalid",
        observed_at_utc="2026-01-02T00:00:00+00:00",
    )

    row = con.execute(
        "SELECT outcome,outcome_status,source,observed_at_utc "
        "FROM event_outcome WHERE event_id='e2'"
    ).fetchone()
    assert row == (
        "A",
        "VERIFIED",
        "source",
        "2026-01-02T00:00:00+00:00",
    )


def test_regression_contract_does_not_use_replace() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1] / "src/outcome_backfill.py"
    ).read_text(encoding="utf-8")
    assert "INSERT OR REPLACE INTO event_outcome" not in text
    assert "WHERE event_outcome.outcome_status <> 'VERIFIED'" in text


if __name__ == "__main__":
    test_verified_outcome_is_immutable()
    test_deferred_outcome_can_be_upgraded_once()
    test_regression_contract_does_not_use_replace()
    print("OUTCOME_BACKFILL_LINEAGE=PASS")
