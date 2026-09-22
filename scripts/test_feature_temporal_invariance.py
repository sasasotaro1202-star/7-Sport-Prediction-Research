from __future__ import annotations

import math
import sqlite3

from src import research_cycle_v4 as research


def build_fixture() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE event(
          event_id TEXT PRIMARY KEY, sport TEXT, competition_id TEXT,
          event_time_utc TEXT, status TEXT
        );
        CREATE TABLE event_participant(
          event_id TEXT, participant_id TEXT, side TEXT
        );
        CREATE TABLE event_outcome(
          event_id TEXT PRIMARY KEY, sport TEXT, side_a_participant_id TEXT,
          side_b_participant_id TEXT, outcome TEXT, score_a REAL, score_b REAL,
          outcome_status TEXT, source TEXT, source_url TEXT,
          observed_at_utc TEXT, quality_status TEXT, reason TEXT
        );
        CREATE TABLE source_snapshot(
          snapshot_id TEXT PRIMARY KEY, source TEXT, source_url TEXT,
          source_available_at_utc TEXT, event_time_utc TEXT,
          availability_status TEXT
        );
        CREATE TABLE match_stats(
          stat_id TEXT PRIMARY KEY, event_id TEXT, participant_id TEXT,
          sport TEXT, stat_name TEXT, value_num REAL, effective_at_utc TEXT,
          observed_at_utc TEXT, source TEXT, source_url TEXT
        );
        """
    )
    fighters = [("a", "b"), ("a", "c"), ("a", "d")]
    times = ["2025-01-01T12:00:00+00:00", "2025-01-10T12:00:00+00:00", "2025-01-20T12:00:00+00:00"]
    outcomes = ["A", "B", "A"]
    for i, ((fa, fb), ts, outcome) in enumerate(zip(fighters, times, outcomes), 1):
        eid = f"e{i}"
        c.execute(
            "INSERT INTO event VALUES(?,?,?,?,?)",
            (eid, "ufc", "UFC", ts, "COMPLETED"),
        )
        c.execute("INSERT INTO event_participant VALUES(?,?,?)", (eid, fa, "A"))
        c.execute("INSERT INTO event_participant VALUES(?,?,?)", (eid, fb, "B"))
        url = f"https://example.test/{eid}"
        avail = "2024-12-31T00:00:00+00:00"
        c.execute(
            "INSERT INTO source_snapshot VALUES(?,?,?,?,?,?)",
            (f"s{i}", "fixture", url, avail, ts, "EXACT"),
        )
        c.execute(
            "INSERT INTO event_outcome VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "ufc", fa, fb, outcome, 1.0, 0.0, "VERIFIED", "fixture", url,
             avail, "PIT_REQUIRES_REPLAY", ""),
        )
        for pid, value in ((fa, 10.0 + i), (fb, 5.0 + i)):
            c.execute(
                "INSERT INTO match_stats VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f"{eid}-{pid}", eid, pid, "ufc", "sig_str", value, ts, avail, "fixture", url),
            )
    c.commit()
    return c


def event_features(c: sqlite3.Connection, event_id: str) -> dict[str, float]:
    rows, _ = research.build(c, "ufc")
    for eid, _, _, features in rows:
        if eid == event_id:
            return features
    raise AssertionError(f"missing feature row: {event_id}")


def assert_same(a: dict[str, float], b: dict[str, float]) -> None:
    assert set(a) == set(b)
    for key in a:
        x, y = a[key], b[key]
        if isinstance(x, float) and math.isnan(x) and isinstance(y, float) and math.isnan(y):
            continue
        assert x == y, f"future mutation changed prior feature: {key}: {x!r} != {y!r}"


def main() -> int:
    c = build_fixture()
    before = event_features(c, "e2")

    # Mutate only data belonging to the future event e3.
    c.execute("UPDATE event_outcome SET outcome='B', score_a=0.0, score_b=1.0 WHERE event_id='e3'")
    c.execute("UPDATE match_stats SET value_num=9999.0 WHERE event_id='e3'")
    c.commit()

    after = event_features(c, "e2")
    assert_same(before, after)

    print("TEMPORAL_FEATURE_IMMUTABILITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
