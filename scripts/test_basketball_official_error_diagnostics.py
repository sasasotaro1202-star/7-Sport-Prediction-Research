#!/usr/bin/env python3
from __future__ import annotations

import src.basketball_cdn_backfill as m


class DummyConnection:
    def commit(self):
        pass


def main() -> int:
    current_season_year = (
        m.datetime.now(m.timezone.utc).year
        if m.datetime.now(m.timezone.utc).month >= 9
        else m.datetime.now(m.timezone.utc).year - 1
    )
    original_get = m.get

    def fail_get(*_args, **_kwargs):
        raise RuntimeError("synthetic_network_failure")

    m.get = fail_get
    try:
        total, errors, attempted, empty_pages = m.collect_official(
            DummyConnection(), [current_season_year]
        )
    finally:
        m.get = original_get

    assert total == 0, total
    assert attempted == 13, attempted
    assert len(errors) == 13, len(errors)
    assert all(e["error_type"] == "RuntimeError" for e in errors)
    assert empty_pages == 0
    assert empty_pages == 0
    assert all(
        e["url"].startswith("https://www.bleague.jp/schedule/")
        or e["url"] == m.BLEAGUE_SCHEDULE_FALLBACK
        for e in errors
    )
    assert errors[-1]["url"] == m.BLEAGUE_SCHEDULE_FALLBACK
    assert all(e["season_year"] == current_season_year for e in errors)
    # Also verify parser-zero is a distinct status without network access.
    calls = {"n": 0}
    original_get = m.get
    original_parse = m.parse_schedule_page

    def empty_get(*_args, **_kwargs):
        calls["n"] += 1
        return "<html></html>", "2026-10-03T00:00:00+00:00", {}

    m.get = empty_get
    m.parse_schedule_page = lambda *_args, **_kwargs: 0
    try:
        total2, errors2, attempted2, empty_pages2 = m.collect_official(
            DummyConnection(), [current_season_year]
        )
    finally:
        m.get = original_get
        m.parse_schedule_page = original_parse

    assert total2 == 0
    assert errors2 == []
    assert attempted2 == 13
    assert empty_pages2 == 13
    assert calls["n"] == 13

    print("BASKETBALL_OFFICIAL_ERROR_DIAGNOSTICS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
