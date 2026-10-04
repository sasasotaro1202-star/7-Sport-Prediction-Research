#!/usr/bin/env python3
from __future__ import annotations

import src.basketball_cdn_backfill as m


class DummyConnection:
    def commit(self):
        pass


def _schedule_csv() -> str:
    return (
        "ScheduleKey,HomeTeamId,AwayTeamId,Date,Season\n"
        "synthetic-key,1,2,2020-01-01,2020\n"
    )


def _summary_csv() -> str:
    fields = ["PTS", "TR", "AS", "ST", "BS", "TO", "F2GM", "F2GA", "F3GM", "F3GA", "FTM", "FTA"]
    header = "ScheduleKey,TeamId," + ",".join(fields) + "\n"
    row1 = "synthetic-key,1," + ",".join(["1"] * len(fields)) + "\n"
    row2 = "synthetic-key,2," + ",".join(["2"] * len(fields)) + "\n"
    return header + row1 + row2


def _teams_csv() -> str:
    return (
        "Season,TeamId,NameShort,NameLong\n"
        "2020,1,Home,Home\n"
        "2020,2,Away,Away\n"
    )


def main() -> int:
    original_get = m.get
    original_upsert_event = m.upsert_event
    original_add_snapshot = m.add_snapshot
    calls = {"upsert": 0}

    def fake_get(url, timeout=45):
        if "teams.csv" in url:
            return _teams_csv(), "2026-10-04T00:00:00+00:00", {}
        if "games_summary_" in url:
            return _summary_csv(), "2026-10-04T00:00:00+00:00", {}
        return _schedule_csv(), "2026-10-04T00:00:00+00:00", {}

    def failing_upsert_event(*_args, **_kwargs):
        calls["upsert"] += 1
        raise ValueError("synthetic_row_failure")

    m.get = fake_get
    m.upsert_event = failing_upsert_event
    m.add_snapshot = lambda *_args, **_kwargs: None
    try:
        total, warnings = m.collect_historical_bleaguer(DummyConnection())
    finally:
        m.get = original_get
        m.upsert_event = original_upsert_event
        m.add_snapshot = original_add_snapshot

    assert total == 0
    assert calls["upsert"] == len(m.SEASONS)
    assert len(warnings) == len(m.SEASONS)
    assert all(w["stage"] == "event_row_materialization" for w in warnings)
    assert all(w["schedule_key"] == "synthetic-key" for w in warnings)
    assert all(w["error_type"] == "ValueError" for w in warnings)
    assert all(w["error"] == "ValueError('synthetic_row_failure')" for w in warnings)

    print("BLEAGUE_HISTORICAL_ERROR_OBSERVABILITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
