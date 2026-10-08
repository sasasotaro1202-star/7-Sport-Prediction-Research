#!/usr/bin/env python3
from __future__ import annotations

import sqlite3

from src.quality_gate import pit_replay_quality


def main() -> int:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE pit_replay(replay_status TEXT, leakage_status TEXT)"
    )
    con.executemany(
        "INSERT INTO pit_replay VALUES (?, ?)",
        [
            ("EXACT", "PASS"),
            ("EXACT", "CLEAN"),
            ("REPLAYABLE", "CLEAN"),
            ("REPLAYABLE", "CLEAN"),
            ("REPLAYABLE", "UNKNOWN"),
            ("DEFERRED", "CLEAN"),
            ("BROKEN", "FAIL"),
        ],
    )

    leak, exact, replayable = pit_replay_quality(con)

    # EXACT remains separate from the canonical REPLAYABLE status.
    assert leak == 1, leak
    assert exact == 2, exact
    assert replayable == 2, replayable

    con.close()
    print("QUALITY_GATE_PIT_REPLAY_STATUS=PASS")
    print("EXACT_CLEAN=2")
    print("REPLAYABLE_CLEAN=2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
