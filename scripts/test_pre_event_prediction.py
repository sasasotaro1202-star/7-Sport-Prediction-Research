from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile

from src.competition_profiles import resolve_profile
from src.future_predictor import _future_events, _prediction_timing
from src.pre_event_prediction_audit import audit


def main() -> None:
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE event(
            event_id TEXT PRIMARY KEY,
            sport TEXT,
            event_time_utc TEXT,
            status TEXT,
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
        "INSERT INTO event VALUES (?,?,?,?,?)",
        [
            ("b1", "basketball", t30, "SCHEDULED", "B.LEAGUE"),
            ("b2", "basketball", t30, "SCHEDULED", "OTHER LEAGUE"),
            ("b3", "basketball", t50, "SCHEDULED", "B.LEAGUE"),
            ("v1", "volleyball", t30, "SCHEDULED", "Asian Games Volleyball"),
            ("x1", "basketball", t30, "COMPLETED", "B.LEAGUE"),
        ],
    )
    c.commit()

    window = _future_events(
        c, "basketball", now, min_lead_minutes=25, max_lead_minutes=60
    )
    assert "b1" in window, window
    assert "b3" in window, window
    assert window["b3"]["lead_minutes"] == 50.0, window
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
    # 30 minutes is a guideline: a prediction with a nearby cutoff is acceptable.
    c.execute("CREATE TABLE forward_prediction( prediction_id TEXT PRIMARY KEY, event_id TEXT, market TEXT, prediction_cutoff_at_utc TEXT, created_at_utc TEXT, strategy TEXT, model_version TEXT )")
    cutoff_early = now + timedelta(minutes=15)
    c.execute(
        "INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?)",
        ("p1","b1","winner",cutoff_early.isoformat(),(now + timedelta(minutes=2)).isoformat(),"test","test")
    )
    c.commit()
    fd, name = tempfile.mkstemp(prefix="pre-event-guideline-", suffix=".sqlite")
    __import__("os").close(fd)
    db = Path(name)
    try:
        disk = sqlite3.connect(db)
        disk.executescript("""
            CREATE TABLE event(
                event_id TEXT PRIMARY KEY,
                sport TEXT,
                event_time_utc TEXT,
                status TEXT,
                competition_id TEXT
            );
            CREATE TABLE event_participant(
                event_id TEXT,
                participant_id TEXT,
                side TEXT
            );
            CREATE TABLE forward_prediction(
                prediction_id TEXT PRIMARY KEY,
                event_id TEXT,
                market TEXT,
                prediction_cutoff_at_utc TEXT,
                created_at_utc TEXT,
                strategy TEXT,
                model_version TEXT
            );
        """)
        disk.execute("INSERT INTO event VALUES (?,?,?,?,?,?)", ("b1","basketball",t30,"SCHEDULED","B.LEAGUE"))
        disk.execute("INSERT INTO event_participant VALUES (?,?,?)", ("b1","a","A"))
        disk.execute("INSERT INTO event_participant VALUES (?,?,?)", ("b1","b","B"))
        disk.execute("INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?)", ("p1","b1","winner",cutoff_early.isoformat(),(now + timedelta(minutes=2)).isoformat(),"test","test"))
        disk.commit()
        disk.close()
        ar = audit(db, "basketball", now, 25, 60, 30)
        assert ar["status"] == "PASS", ar
        assert ar["predicted_in_guideline_window"] == 1, ar
        assert not ar["missing_predictions"], ar
    finally:
        db.unlink(missing_ok=True)
    c.close()
    c.close()
    print("PRE_EVENT_PREDICTION_CONTRACT=PASS")


if __name__ == "__main__":
    main()
