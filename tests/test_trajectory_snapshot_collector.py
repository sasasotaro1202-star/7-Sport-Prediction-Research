from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import trajectory_snapshot_collector as collector


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE event (
            event_id TEXT PRIMARY KEY, sport TEXT, competition_id TEXT,
            event_time_utc TEXT, event_end_time_utc TEXT, status TEXT
        );
        CREATE TABLE event_participant (
            event_id TEXT, participant_id TEXT, team_id TEXT, side TEXT
        );
        CREATE TABLE match_stats (
            stat_id TEXT PRIMARY KEY, event_id TEXT, participant_id TEXT,
            team_id TEXT, sport TEXT, stat_name TEXT, value_num REAL,
            observed_at_utc TEXT, effective_at_utc TEXT, source TEXT, source_url TEXT
        );
        CREATE TABLE source_snapshot (
            snapshot_id TEXT PRIMARY KEY, sport TEXT, source TEXT,
            source_url TEXT, event_time_utc TEXT, source_available_at_utc TEXT,
            availability_status TEXT
        );
        CREATE TABLE event_outcome (
            event_id TEXT PRIMARY KEY, sport TEXT, outcome TEXT,
            outcome_status TEXT, source TEXT, source_url TEXT,
            observed_at_utc TEXT
        );
        """
    )


def seed(con: sqlite3.Connection, good: bool = True) -> None:
    start = BASE
    end = BASE + timedelta(minutes=40)
    con.execute(
        "INSERT INTO event VALUES (?,?,?,?,?,?)",
        ("e1", "basketball", "b.league", start.isoformat(), end.isoformat(), "COMPLETED"),
    )
    con.executemany(
        "INSERT INTO event_participant VALUES (?,?,?,?)",
        [("e1", "a", None, "A"), ("e1", "b", None, "B")],
    )
    source_url = "https://example.test/e1"
    con.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?)",
        ("ss1", "basketball", "test", source_url, start.isoformat(),
         (start - timedelta(minutes=5)).isoformat() if good else (end + timedelta(minutes=1)).isoformat(),
         "EXACT"),
    )
    stats = []
    for j, minute in enumerate((5, 10, 15, 20, 25, 30)):
        observed = start + timedelta(minutes=minute)
        for pid, value in (("a", 10 + minute), ("b", 8 + minute)):
            stats.append(
                (
                    f"s{j}{pid}", "e1", pid, None, "basketball", "points",
                    float(value), observed.isoformat(), observed.isoformat(),
                    "test", source_url,
                )
            )
    con.executemany(
        "INSERT INTO match_stats VALUES (?,?,?,?,?,?,?,?,?,?,?)", stats
    )
    con.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?,?,?,?)",
        ("e1", "basketball", "A", "VERIFIED", "test", source_url, end.isoformat()),
    )
    con.commit()


def test_good_pit_produces_snapshots() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "sports.sqlite"
        con = sqlite3.connect(db)
        schema(con)
        seed(con, good=True)
        con.close()
        out = collector.collect("basketball", db)
        assert out["status"] == "READY"
        assert out["snapshot_count"] > 0
        assert out["outcome_count"] == 1
        assert all(
            datetime.fromisoformat(x["source_available_at_utc"].replace("Z", "+00:00"))
            <= datetime.fromisoformat(x["prediction_time_utc"].replace("Z", "+00:00"))
            for x in out["snapshots"]
        )


def test_bad_pit_is_fail_closed_for_snapshots() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "sports.sqlite"
        con = sqlite3.connect(db)
        schema(con)
        seed(con, good=False)
        con.close()
        out = collector.collect("basketball", db)
        assert out["status"] == "BLOCKED"
        assert out["snapshot_count"] == 0


if __name__ == "__main__":
    test_good_pit_produces_snapshots()
    test_bad_pit_is_fail_closed_for_snapshots()
    print("TRAJECTORY_SNAPSHOT_COLLECTOR_TEST=PASS")
