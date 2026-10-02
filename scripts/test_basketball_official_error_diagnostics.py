#!/usr/bin/env python3
from __future__ import annotations

import src.basketball_cdn_backfill as m


class DummyConnection:
    def commit(self):
        pass


def main() -> int:
    original_get = m.get

    def fail_get(*_args, **_kwargs):
        raise RuntimeError("synthetic_network_failure")

    m.get = fail_get
    try:
        total, errors, attempted = m.collect_official(DummyConnection(), [2026])
    finally:
        m.get = original_get

    assert total == 0, total
    assert attempted == 12, attempted
    assert len(errors) == 12, len(errors)
    assert all(e["error_type"] == "RuntimeError" for e in errors)
    assert all(e["url"].startswith("https://www.bleague.jp/schedule/") for e in errors)
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
        total2, errors2, attempted2, empty_pages2 = m.collect_official(DummyConnection(), [2026])
    finally:
        m.get = original_get
        m.parse_schedule_page = original_parse

    assert total2 == 0
    assert errors2 == []
    assert attempted2 == 12
    assert empty_pages2 == 12

    print("BASKETBALL_OFFICIAL_ERROR_DIAGNOSTICS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
