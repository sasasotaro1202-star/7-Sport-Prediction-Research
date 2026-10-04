#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import src.seven_sport_production as m


class DummyConnection:
    def close(self):
        pass


def main() -> int:
    original = {
        "ROOT": m.ROOT,
        "connect": m.connect,
        "init_db": m.init_db,
        "counts": m.counts,
        "collect_official": None,
    }

    def fake_connect():
        return DummyConnection()

    def fake_counts(_c):
        return {
            "event": 0,
            "participant": 0,
            "event_participant": 0,
            "match_stats": 0,
            "source_snapshot": 0,
            "pit_replay": 0,
            "collection_state": 0,
        }

    def fake_collect(_c, _seasons):
        return 0, [], 13, 13

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "results/v45").mkdir(parents=True)

        m.ROOT = root
        m.connect = fake_connect
        m.init_db = lambda _c: None
        m.counts = fake_counts

        # The main module imports collect_official lazily inside its basketball
        # branch, so inject the test double into the backfill module itself.
        import src.basketball_cdn_backfill as backfill

        original_backfill = backfill.collect_official
        backfill.collect_official = fake_collect
        old_argv = sys.argv
        sys.argv = ["test", "--sport", "basketball", "--days-forward", "7"]
        try:
            try:
                m.main()
            except SystemExit as exc:
                assert exc.code == 1, exc.code
            else:
                raise AssertionError("parser-zero must fail closed")
        finally:
            sys.argv = old_argv
            backfill.collect_official = original_backfill
            m.ROOT = original["ROOT"]
            m.connect = original["connect"]
            m.init_db = original["init_db"]
            m.counts = original["counts"]

        report = json.loads(
            (root / "results/v45/production_run.json").read_text(encoding="utf-8")
        )
        assert report["status"] == "FAILED"
        assert report["deltas"]["event"] == 0
        assert report["errors"][0]["error_type"] == "PARSER_ZERO"
        assert report["errors"][0]["requests"] == 13
        assert report["errors"][0]["empty_pages"] == 13

    print("BASKETBALL_ZERO_PROPAGATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
