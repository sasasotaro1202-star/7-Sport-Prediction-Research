"""Offline unit tests for WTA public schedule normalization helpers.

These tests do not call the external WTA service and therefore remain
deterministic/free in CI.
"""
from datetime import datetime, timezone

from src.seven_sport_production import _first_time, _nested_player_name


def main():
    assert _nested_player_name({"fullName": "Alice Example"}) == "Alice Example"
    assert _nested_player_name({"player": {"displayName": "Bob Example"}}) == "Bob Example"
    assert _nested_player_name("  Carol   Example ") == "Carol Example"
    assert _nested_player_name(None) is None

    dt = _first_time({"startTimestamp": 1_759_000_000_000})
    parsed = datetime.fromisoformat(dt)
    assert parsed.tzinfo == timezone.utc
    assert parsed.year >= 2025

    assert _first_time({"startDate": "2026-09-25T12:34:56Z"}) == "2026-09-25T12:34:56+00:00"
    assert _first_time("2026-09-25T12:34:56Z") == "2026-09-25T12:34:56+00:00"

    print("WTA helper tests: PASS")


if __name__ == "__main__":
    main()
