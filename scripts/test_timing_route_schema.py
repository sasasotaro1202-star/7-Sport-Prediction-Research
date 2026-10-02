#!/usr/bin/env python3
from __future__ import annotations

import sqlite3

from src.timing_route_builder import _prepare_rows


def main() -> int:
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE event(
            event_id TEXT PRIMARY KEY,
            sport TEXT NOT NULL,
            competition_id TEXT,
            season TEXT,
            stage TEXT,
            round TEXT,
            event_time_utc TEXT,
            event_end_time_utc TEXT,
            event_type TEXT,
            status TEXT,
            source_count INTEGER DEFAULT 0,
            quality_status TEXT NOT NULL
        );
        CREATE TABLE event_outcome(
            event_id TEXT PRIMARY KEY,
            sport TEXT NOT NULL,
            side_a_participant_id TEXT,
            side_b_participant_id TEXT,
            outcome TEXT,
            score_a REAL,
            score_b REAL,
            outcome_status TEXT NOT NULL,
            source TEXT,
            source_url TEXT,
            observed_at_utc TEXT NOT NULL,
            quality_status TEXT NOT NULL,
            reason TEXT
        );
        CREATE TABLE forward_prediction(
            prediction_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            sport TEXT NOT NULL,
            market TEXT NOT NULL,
            prediction_cutoff_at_utc TEXT NOT NULL,
            generated_at_utc TEXT NOT NULL,
            probability_side_a REAL,
            probability_side_b REAL,
            strategy TEXT,
            model_version TEXT,
            feature_version TEXT,
            features_json TEXT NOT NULL,
            feature_snapshot_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN'
        );
        """
    )
    con.execute(
        "INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "e1", "basketball", "B.LEAGUE", "2025-26", "regular",
            "1", "2026-01-01T11:00:00+00:00", None, "match",
            "COMPLETED", 1, "VERIFIED",
        ),
    )
    con.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "e1", "basketball", "a", "b", "A", 90, 80,
            "VERIFIED", "test", "test://outcome",
            "2026-01-01T12:00:00+00:00", "VERIFIED", "test",
        ),
    )
    con.execute(
        "INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p1", "e1", "basketball", "winner",
            "2026-01-01T10:00:00+00:00", "2026-01-01T10:00:00+00:00",
            0.70, 0.30, "test", "test", "test", "{}",
            "hash", "OPEN",
        ),
    )
    result = _prepare_rows(con, "basketball", {60})
    assert result, "canonical event schema row was not prepared"
    assert "basketball:bleague" in result
    assert 60 in result["basketball:bleague"]
    assert "e1" in result["basketball:bleague"][60]
    candidate = result["basketball:bleague"][60]["e1"]
    assert candidate["competition_id"] == "B.LEAGUE"
    assert candidate["profile_id"] == "basketball:bleague"
    con.close()
    print("TIMING_ROUTE_CANONICAL_SCHEMA=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
