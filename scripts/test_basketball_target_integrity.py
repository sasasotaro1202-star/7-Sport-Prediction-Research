#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from src.competition_profiles import resolve_profile
from src.future_predictor import _prior_record
from src.research_cycle_v4 import target_event

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    collector = (ROOT / "src/seven_sport_production.py").read_text(encoding="utf-8")
    assert "from src.basketball_cdn_backfill import collect_official" in collector
    assert "collect_espn(c,h,sport,['nba','wnba','mens-college-basketball']" not in collector

    guard = (ROOT / "src/collection_guard.py").read_text(encoding="utf-8")
    assert "%b.premier%" in guard
    assert "%b.one%" in guard
    assert "%b.two%" in guard

    assert target_event("basketball", "Chiba Jets vs Shimane", "B.PREMIER")
    assert resolve_profile("basketball", "B.PREMIER", "Chiba Jets vs Shimane")["profile_id"] == "basketball:bleague"
    assert resolve_profile("basketball", "B.ONE", "B.ONE")["profile_id"] == "basketball:bleague"

    with tempfile.NamedTemporaryFile(suffix=".sqlite") as fh:
        db = sqlite3.connect(fh.name)
        db.executescript("""
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
                event_id TEXT PRIMARY KEY,
                outcome TEXT,
                outcome_status TEXT,
                source_url TEXT
            );
            CREATE TABLE source_snapshot(
                snapshot_id TEXT PRIMARY KEY,
                source TEXT,
                source_url TEXT,
                availability_status TEXT,
                source_available_at_utc TEXT,
                retrieved_at_utc TEXT,
                event_time_utc TEXT
            );
        """)
        cutoff = "2026-10-17T03:05:00+00:00"
        db.executemany(
            "INSERT INTO event VALUES (?,?,?,?)",
            [
                ("exact", "basketball", "2026-01-01T00:00:00+00:00", "COMPLETED"),
                ("retrieval_only", "basketball", "2026-02-01T00:00:00+00:00", "COMPLETED"),
            ],
        )
        db.executemany(
            "INSERT INTO event_participant VALUES (?,?,?)",
            [
                ("exact", "team_a", "A"), ("exact", "team_b", "B"),
                ("retrieval_only", "team_a", "A"), ("retrieval_only", "team_b", "B"),
            ],
        )
        db.executemany(
            "INSERT INTO event_outcome VALUES (?,?,?,?)",
            [
                ("exact", "A", "VERIFIED", "https://example.test/exact"),
                ("retrieval_only", "A", "VERIFIED", "https://example.test/retrieval"),
            ],
        )
        db.executemany(
            "INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?)",
            [
                # Immutable file provenance may represent a whole season file
                # and therefore legitimately have a NULL event_time_utc.
                ("s1", "bleaguer-github", "https://example.test/exact", "EXACT",
                 "2025-12-01T00:00:00+00:00", "2026-10-03T00:00:00+00:00", None),
                ("s2", "test", "https://example.test/retrieval", "UNVERIFIABLE",
                 None, "2025-12-01T00:00:00+00:00",
                 "2026-02-01T00:00:00+00:00"),
            ],
        )
        db.commit()

        starts_a, wins_a, _ = _prior_record(db, "basketball", "team_a", cutoff)
        starts_b, wins_b, _ = _prior_record(db, "basketball", "team_b", cutoff)
        assert (starts_a, wins_a) == (1, 1), (starts_a, wins_a)
        assert (starts_b, wins_b) == (1, 0), (starts_b, wins_b)
        db.close()

    print("BASKETBALL_TARGET_INTEGRITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
