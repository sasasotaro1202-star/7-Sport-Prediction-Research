"""Deterministic F1 event-status regression tests."""
from datetime import datetime, timezone
from src.seven_sport_production import f1_event_status

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

def main():
    assert f1_event_status("2026-10-11T14:00:00+00:00", [], NOW) == "SCHEDULED"
    assert f1_event_status("2026-10-11T14:00:00+00:00", [{"Driver": {"givenName": "A"}}], NOW) == "COMPLETED"
    assert f1_event_status("2026-09-20T14:00:00+00:00", [], NOW) == "UNKNOWN"
    assert f1_event_status(None, [], NOW) == "UNKNOWN"
    source = __import__("pathlib").Path("src/seven_sport_production.py").read_text(encoding="utf-8")
    assert "upsert_ep(c,eid,pid,None,None,'driver'" in source
    assert "role describes the participant's actual" in source
    print("F1 event status tests: PASS")

if __name__ == "__main__":
    main()
