#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.competition_profiles import resolve_profile
from src.future_predictor import _prior_record
from src.research_cycle_v4 import target_event

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    collector = (ROOT / "src/seven_sport_production.py").read_text(encoding="utf-8")
    assert "from src.basketball_cdn_backfill import collect_official" in collector
    assert "collect_espn(c,h,'basketball',['nba'],start,end,store_outcomes=True)" in collector

    assert resolve_profile("basketball", "NBA", None)["matched"] is True
    assert target_event("basketball", "Boston Celtics vs Los Angeles Lakers", "NBA") is True

    for tier in ("B.PREMIER", "B.ONE", "B.TWO"):
        assert resolve_profile("basketball", tier, None)["matched"] is True
        assert target_event("basketball", "Chiba Jets vs Shimane Susanoo Magic", tier) is True

    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE event(
          event_id TEXT PRIMARY KEY, sport TEXT, event_time_utc TEXT,
          status TEXT, competition_id TEXT
        );
        CREATE TABLE event_participant(
          event_id TEXT, participant_id TEXT, side TEXT
        );
        CREATE TABLE event_outcome(
          event_id TEXT, sport TEXT, outcome TEXT,
          outcome_status TEXT, source_url TEXT
        );
        CREATE TABLE source_snapshot(
          snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
          sport TEXT, source TEXT, source_url TEXT, event_time_utc TEXT,
          retrieved_at_utc TEXT, source_available_at_utc TEXT,
          availability_status TEXT
        );
        """
    )

    cutoff = "2026-10-03T06:00:00+00:00"
    historical_event = "2026-09-30T10:00:00+00:00"
    con.execute(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        ("e_exact", "basketball", historical_event, "COMPLETED", "B.PREMIER"),
    )
    con.execute("INSERT INTO event_participant VALUES (?,?,?)", ("e_exact", "p1", "A"))
    con.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?,?)",
        ("e_exact", "basketball", "A", "VERIFIED", "https://example.test/games_201920_summary.csv"),
    )
    # One immutable CSV covers many events, so its source snapshot is
    # intentionally event_time=NULL. Its exact blob provenance proves
    # availability before the prediction cutoff.
    con.execute(
        """INSERT INTO source_snapshot
           (sport,source,source_url,event_time_utc,retrieved_at_utc,
            source_available_at_utc,availability_status)
           VALUES (?,?,?,?,?,?,?)""",
        ("basketball", "bleaguer-github",
         "https://example.test/games_201920_summary.csv", None,
         "2026-10-03T12:00:00+00:00", "2020-01-10T00:00:00+00:00", "EXACT"),
    )

    con.execute(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        ("e_retrieval_only", "basketball", "2026-09-29T10:00:00+00:00", "COMPLETED", "B.PREMIER"),
    )
    con.execute("INSERT INTO event_participant VALUES (?,?,?)", ("e_retrieval_only", "p2", "A"))
    con.execute(
        "INSERT INTO event_outcome VALUES (?,?,?,?,?)",
        ("e_retrieval_only", "basketball", "A", "VERIFIED", "https://example.test/retrieval_only.csv"),
    )
    con.execute(
        """INSERT INTO source_snapshot
           (sport,source,source_url,event_time_utc,retrieved_at_utc,
            source_available_at_utc,availability_status)
           VALUES (?,?,?,?,?,?,?)""",
        ("basketball", "bleaguer-github",
         "https://example.test/retrieval_only.csv", None,
         "2026-09-30T00:00:00+00:00", None, "UNVERIFIABLE"),
    )

    starts1, wins1, _ = _prior_record(con, "basketball", "p1", cutoff)
    starts2, wins2, _ = _prior_record(con, "basketball", "p2", cutoff)
    assert (starts1, wins1) == (1, 1)
    assert (starts2, wins2) == (0, 0)
    con.close()

    print("BASKETBALL_TARGET_PIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
