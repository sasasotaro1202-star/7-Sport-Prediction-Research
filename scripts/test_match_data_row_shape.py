#!/usr/bin/env python3
"""Regression test for the SQLite row-shape contract in match_data_expansion."""

from __future__ import annotations

import sqlite3

from src.match_data_expansion import (
    EVENT_ROW_COLUMNS,
    _event_row_to_dict,
    select_events,
)


def main() -> int:
    values = (
        "event-1",
        "volleyball",
        "2026-10-04T12:00:00+00:00",
        "MATCH",
        "SCHEDULED",
        "https://example.test/event-1",
    )

    tuple_event = _event_row_to_dict(values)
    assert list(tuple_event) == list(EVENT_ROW_COLUMNS)
    assert tuple_event["event_id"] == "event-1"
    assert tuple_event["source_url"] == "https://example.test/event-1"

    row_con = sqlite3.connect(":memory:")
    row_con.row_factory = sqlite3.Row
    row = row_con.execute(
        "SELECT ? AS event_id, ? AS sport, ? AS event_time_utc, "
        "? AS event_type, ? AS status, ? AS source_url",
        values,
    ).fetchone()
    mapping_event = _event_row_to_dict(row)
    assert mapping_event == tuple_event

    event_con = sqlite3.connect(":memory:")
    event_con.executescript(
        """
        CREATE TABLE event(
            event_id TEXT,
            sport TEXT,
            event_time_utc TEXT,
            event_type TEXT,
            status TEXT
        );
        CREATE TABLE event_participant(
            event_id TEXT,
            participant_id TEXT,
            side TEXT,
            source_url TEXT
        );
        """
    )
    import datetime as _dt

    future = (
        _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=30)
    ).isoformat()
    event_con.execute(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        ("event-3", "volleyball", future, "MATCH", "SCHEDULED"),
    )
    event_con.execute(
        "INSERT INTO event_participant VALUES (?,?,?,?)",
        ("event-3", "team-a", "A", "https://example.test/event-3"),
    )
    event_con.commit()
    selected = select_events(
        event_con, "volleyball", horizon_days=1, max_events=10
    )
    assert len(selected) == 1, selected
    selected_event = _event_row_to_dict(selected[0])
    assert selected_event["event_id"] == "event-3"
    assert selected_event["source_url"] == "https://example.test/event-3"

    dict_event = _event_row_to_dict({"event_id": "event-2", "sport": "basketball"})
    assert dict_event["event_id"] == "event-2"

    try:
        _event_row_to_dict(("only-one-field",))
    except TypeError:
        pass
    try:
        _event_row_to_dict("event-id-as-a-string")
    except TypeError:
        pass
    else:
        raise AssertionError("short row must fail closed")

    print("MATCH_DATA_EVENT_ROW_NORMALIZATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
