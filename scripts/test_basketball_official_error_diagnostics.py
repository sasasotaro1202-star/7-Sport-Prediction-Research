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
    print("BASKETBALL_OFFICIAL_ERROR_DIAGNOSTICS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
