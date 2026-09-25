"""Regression tests for prediction-cutoff PIT in future priors."""

import sqlite3
from src.future_predictor import _prior_record


class FakeResult:
    def fetchone(self):
        return (0,)


class FakeDB:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return FakeResult()


def assert_query_shape():
    cutoff = "2026-09-25T10:00:00+00:00"
    db = FakeDB()
    starts, wins, rate = _prior_record(db, "tennis", "p1", cutoff)
    assert (starts, wins) == (0, 0)
    assert rate == 0.5
    assert len(db.calls) == 2
    for sql, params in db.calls:
        assert "ss.event_time_utc=e.event_time_utc" in sql
        assert "datetime(ss.source_available_at_utc) <= datetime(?)" in sql
        assert "datetime(ss.retrieved_at_utc) <= datetime(?)" in sql
        assert params[-3:] == (cutoff, cutoff, cutoff)
        assert "e.event_time_utc < ?" in sql
        assert "ss.source_available_at_utc IS NULL" in sql
        if "o.outcome=ep.side" in sql:
            assert "COUNT(DISTINCT e.event_id)" in sql


def build_db():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE event(
            event_id TEXT PRIMARY KEY,
            sport TEXT,
            event_time_utc TEXT,
            status TEXT
        );
        CREATE TABLE event_participant(
            event_id TEXT,
            participant_id TEXT,
            side TEXT
        );
        CREATE TABLE event_outcome(
            event_id TEXT,
            outcome_status TEXT,
            outcome TEXT,
            source_url TEXT
        );
        CREATE TABLE source_snapshot(
            source_url TEXT,
            event_time_utc TEXT,
            availability_status TEXT,
            source_available_at_utc TEXT,
            retrieved_at_utc TEXT
        );
        """
    )
    return db


def assert_pit_behavior():
    cutoff = "2026-09-25T10:00:00+00:00"

    db = build_db()
    db.execute(
        "INSERT INTO event VALUES (?,?,?,?)",
        ("e1", "tennis", "2026-09-24T10:00:00+00:00", "COMPLETED"),
    )
    db.execute("INSERT INTO event_participant VALUES (?,?,?)", ("e1", "p1", "A"))
    db.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?)",
        ("e1", "VERIFIED", "A", "https://source/e1"),
    )
    # Unknown publication time, retrieved before cutoff: usable for future inference.
    db.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?)",
        (
            "https://source/e1",
            "2026-09-24T10:00:00+00:00",
            "UNVERIFIABLE",
            None,
            "2026-09-25T09:00:00+00:00",
        ),
    )
    # Duplicate snapshot must not double-count the event/win.
    db.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?)",
        (
            "https://source/e1",
            "2026-09-24T10:00:00+00:00",
            "UNVERIFIABLE",
            None,
            "2026-09-25T09:30:00+00:00",
        ),
    )
    # A later retrieval is excluded by the prediction cutoff.
    db.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?)",
        (
            "https://source/e1",
            "2026-09-24T10:00:00+00:00",
            "UNVERIFIABLE",
            None,
            "2026-09-25T11:00:00+00:00",
        ),
    )
    db.commit()

    starts, wins, rate = _prior_record(db, "tennis", "p1", cutoff)
    assert (starts, wins) == (1, 1), (starts, wins)
    assert abs(rate - (2.0 / 3.0)) < 1e-12, rate

    db.close()

    db = build_db()
    db.execute(
        "INSERT INTO event VALUES (?,?,?,?)",
        ("e2", "tennis", "2026-09-24T10:00:00+00:00", "COMPLETED"),
    )
    db.execute("INSERT INTO event_participant VALUES (?,?,?)", ("e2", "p1", "A"))
    db.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?)",
        ("e2", "VERIFIED", "A", "https://source/e2"),
    )
    # Explicit publication after cutoff: do not fall back to retrieval time.
    db.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?)",
        (
            "https://source/e2",
            "2026-09-24T10:00:00+00:00",
            "EXACT",
            "2026-09-25T11:00:00+00:00",
            "2026-09-25T09:00:00+00:00",
        ),
    )
    db.commit()
    starts, wins, rate = _prior_record(db, "tennis", "p1", cutoff)
    assert (starts, wins) == (0, 0), (starts, wins)
    assert rate == 0.5
    db.close()


def main():
    assert_query_shape()
    assert_pit_behavior()
    print("future predictor PIT retrieval-time + dedup test: PASS")


if __name__ == "__main__":
    main()
