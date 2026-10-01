from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta

from src.competition_profiles import resolve_profile
from src.future_predictor import _future_events, _prediction_timing


def main() -> None:
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE event(
            event_id TEXT PRIMARY KEY,
            sport TEXT,
            event_time_utc TEXT,
            status TEXT,
            name TEXT,
            competition_id TEXT
        );
        CREATE TABLE event_participant(
            event_id TEXT,
            participant_id TEXT,
            side TEXT
        );
    """)

    t30 = (now + timedelta(minutes=30)).isoformat()
    t50 = (now + timedelta(minutes=50)).isoformat()
    c.executemany(
        "INSERT INTO event VALUES (?,?,?,?,?,?)",
        [
            ("b1", "basketball", t30, "SCHEDULED", "B.LEAGUE", "B.LEAGUE"),
            ("b2", "basketball", t30, "SCHEDULED", "Other League", "OTHER LEAGUE"),
            ("b3", "basketball", t50, "SCHEDULED", "B.LEAGUE", "B.LEAGUE"),
            ("v1", "volleyball", t30, "SCHEDULED", "Asian Games Volleyball", "Asian Games Volleyball"),
            ("x1", "basketball", t30, "COMPLETED", "B.LEAGUE", "B.LEAGUE"),
        ],
    )
    c.commit()

    window = _future_events(
        c, "basketball", now, min_lead_minutes=25, max_lead_minutes=40
    )
    assert "b1" in window, window
    assert "b3" not in window, window
    assert "x1" not in window, window

    on_time = _prediction_timing(t30, now, 30)
    assert on_time["status"] == "ON_TIME", on_time
    assert on_time["target_cutoff_at_utc"] == now.isoformat(), on_time

    early_now = now - timedelta(minutes=5)
    early = _prediction_timing(t30, early_now, 30)
    assert early["status"] == "EARLY", early

    late_now = now + timedelta(minutes=3)
    late = _prediction_timing(t30, late_now, 30)
    assert late["status"] == "LATE", late

    assert resolve_profile("basketball", "B.LEAGUE", "B.LEAGUE")["matched"]
    assert not resolve_profile("basketball", "Other League", "Other League")["matched"]
    assert resolve_profile("volleyball", "Asian Games Volleyball", "Asian Games Volleyball")["matched"]

    c.close()
    print("PRE_EVENT_PREDICTION_CONTRACT=PASS")


if __name__ == "__main__":
    main()
