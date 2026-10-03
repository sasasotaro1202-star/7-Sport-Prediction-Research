#!/usr/bin/env python3
from __future__ import annotations

from src.ufc_api_backfill import insert_official_jsonapi


class FakeConnection:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, tuple(params)))
        return self


def main() -> int:
    payload = {
        "data": [
            {
                "type": "node--event",
                "id": "event-1",
                "attributes": {
                    "title": "UFC 999",
                    "fight_card_time_main": "2026-10-10T23:00:00+00:00",
                },
                "relationships": {
                    "fights": {
                        "data": [
                            {"type": "node--fight", "id": "fight-1"},
                        ]
                    }
                },
            }
        ],
        "included": [
            {
                "type": "node--fight",
                "id": "fight-1",
                "attributes": {"title": "Alpha vs Beta"},
                "relationships": {
                    "red_corner": {
                        "data": [{"type": "node--athlete", "id": "athlete-a"}]
                    },
                    "blue_corner": {
                        "data": [{"type": "node--athlete", "id": "athlete-b"}]
                    },
                },
            },
            {
                "type": "node--athlete",
                "id": "athlete-a",
                "attributes": {"title": "Alpha"},
            },
            {
                "type": "node--athlete",
                "id": "athlete-b",
                "attributes": {"title": "Beta"},
            },
        ],
    }

    conn = FakeConnection()
    events, fights = insert_official_jsonapi(
        payload,
        conn,
        "https://www.ufc.com/jsonapi/node/event",
    )
    assert (events, fights) == (1, 1)

    sql_blob = "\n".join(sql for sql, _ in conn.executed)
    assert "INSERT INTO event" in sql_blob
    assert "event_participant" in sql_blob
    assert "source_snapshot" in sql_blob

    params_blob = repr(conn.executed)
    assert "Alpha" in params_blob and "Beta" in params_blob
    assert "ufc-official-jsonapi" in params_blob
    assert "ufc-jsonapi-v1" in params_blob

    try:
        insert_official_jsonapi({"data": []}, FakeConnection(), "https://example.invalid")
    except RuntimeError as exc:
        assert "zero event records" in str(exc)
    else:
        raise AssertionError("empty official JSON:API response must fail closed")

    print("UFC_OFFICIAL_JSONAPI=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
