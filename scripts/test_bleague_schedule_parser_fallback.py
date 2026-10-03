#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

import src.basketball_cdn_backfill as m


class DummyConnection:
    def commit(self):
        pass


def current_season_year() -> int:
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 9 else now.year - 1


def main() -> int:
    original_get = m.get
    original_parse = m.parse_schedule_page

    calls: list[str] = []
    parse_calls: list[tuple[str, int, int]] = []

    def empty_get(url, *_args, **_kwargs):
        calls.append(url)
        return "<html></html>", "2026-10-03T00:00:00+00:00", {}

    def gated_parse(_c, _html, _retrieved, url, season_year, month):
        parse_calls.append((url, int(season_year), int(month)))
        # The 13th request is the bounded official legacy current-season
        # fallback. It is intentionally not a new source or a new PIT path.
        return 2 if url == m.BLEAGUE_SCHEDULE_FALLBACK else 0

    m.get = empty_get
    m.parse_schedule_page = gated_parse
    try:
        season = current_season_year()
        total, errors, attempted, empty_pages = m.collect_official(
            DummyConnection(), [season]
        )
    finally:
        m.get = original_get
        m.parse_schedule_page = original_parse

    assert total == 2, total
    assert errors == []
    assert attempted == 13, attempted
    assert empty_pages == 12, empty_pages
    assert calls[:12] == [
        m.BLEAGUE_SCHEDULE.format(month=month, season_year=season)
        for month in range(1, 13)
    ]
    assert calls[12] == m.BLEAGUE_SCHEDULE_FALLBACK
    assert parse_calls[-1] == (m.BLEAGUE_SCHEDULE_FALLBACK, season, 0)

    # Historical/non-current seasons must not receive the current-season
    # fallback. This preserves season boundaries and avoids relabelling.
    calls.clear()
    parse_calls.clear()
    m.get = empty_get
    m.parse_schedule_page = lambda *_args, **_kwargs: 0
    try:
        historical_season = season - 1
        total2, errors2, attempted2, empty_pages2 = m.collect_official(
            DummyConnection(), [historical_season]
        )
    finally:
        m.get = original_get
        m.parse_schedule_page = original_parse

    assert total2 == 0
    assert errors2 == []
    assert attempted2 == 12, attempted2
    assert empty_pages2 == 12, empty_pages2
    assert m.BLEAGUE_SCHEDULE_FALLBACK not in calls

    print("BLEAGUE_SCHEDULE_FALLBACK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
