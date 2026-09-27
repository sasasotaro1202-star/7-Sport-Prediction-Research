from __future__ import annotations

import sqlite3

from src.storage.db_v45 import SCHEMA, _migrate
from scripts.audit_source_feature_usage import audit_sport
from src import research_cycle_v4 as base


def _insert_event(con, eid, when, source):
    con.execute(
        "INSERT INTO event(event_id,sport,competition_id,event_time_utc,status,quality_status) VALUES(?,?,?,?,?,?)",
        (eid, "basketball", "test", when, "scheduled", "VERIFIED"),
    )
    for side, pid in (("A", f"{eid}-a"), ("B", f"{eid}-b")):
        con.execute(
            """
            INSERT INTO participant(participant_id,sport,participant_type,canonical_name,
                                    first_seen_at,last_seen_at)
            VALUES(?,?,?,?,?,?)
            """,
            (pid, "basketball", "player", pid, when, when),
        )
        con.execute(
            """
            INSERT INTO event_participant(event_id,participant_id,side,source,source_url,
                                          effective_at_utc,quality_status)
            VALUES(?,?,?,?,?,?,?)
            """,
            (eid, pid, side, source, "https://example.test/stats", when, "EXACT"),
        )


def main():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    _migrate(con)

    _insert_event(con, "e1", "2026-01-01T12:00:00+00:00", "test_source")
    _insert_event(con, "e2", "2026-01-03T12:00:00+00:00", "test_source")

    con.execute(
        """
        INSERT INTO event_outcome(event_id,sport,outcome,score_a,score_b,outcome_status,
                                  source,source_url,observed_at_utc,quality_status)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        ("e1", "basketball", "A", 80, 70, "VERIFIED", "test_source",
         "https://example.test/stats", "2026-01-01T13:00:00+00:00", "EXACT"),
    )
    con.execute(
        """
        INSERT INTO event_outcome(event_id,sport,outcome,score_a,score_b,outcome_status,
                                  source,source_url,observed_at_utc,quality_status)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        ("e2", "basketball", "B", 72, 75, "VERIFIED", "test_source",
         "https://example.test/stats", "2026-01-03T13:00:00+00:00", "EXACT"),
    )

    snapshot = (
        "snap-e1", "basketball", "test_source", "https://example.test/stats",
        "2026-01-01T10:00:00+00:00", "2026-01-01T10:00:00+00:00",
        "2026-01-01T12:00:00+00:00", "hash-e1", "raw/e1.json",
        "test", "EXACT", "{}",
    )
    con.execute(
        """INSERT INTO source_snapshot(
           snapshot_id,sport,source,source_url,retrieved_at_utc,source_available_at_utc,
           event_time_utc,content_hash,payload_path,parser_version,availability_status,provenance_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        snapshot,
    )
    for eid in ("e1",):
        for pid, value in (("e1-a", 100.0), ("e1-b", 90.0)):
            con.execute(
                """
                INSERT INTO match_stats(
                  stat_id,event_id,participant_id,sport,observed_at_utc,effective_at_utc,
                  stat_name,value_num,source,source_url,quality_status,confidence)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (f"{eid}-{pid}-points", eid, pid, "basketball",
                 "2026-01-01T11:00:00+00:00", "2026-01-01T10:30:00+00:00",
                 "points", value, "test_source", "https://example.test/stats", "EXACT", 1.0),
            )

    registry = {
        "sports": {
            "basketball": [
                {"id": "test_source", "free": True, "integrated": True,
                 "class": "primary", "independence_family": "test-a", "pit": "exact"},
                {"id": "candidate_b", "free": True, "integrated": False,
                 "class": "research_only", "independence_family": "test-b", "pit": "replay_required"},
            ]
        }
    }

    report = audit_sport(con, "basketball", registry)

    assert report["database"]["policy_stats_observed_in_db"] == ["points"]
    assert report["database"]["exact_pit_stat_rows"] == 2
    assert report["strict_feature_matrix"]["build_rows"] >= 1
    assert "points" in report["strict_feature_matrix"]["active_policy_stats"]
    assert report["strict_feature_matrix"]["stat_feature_usage"]["points"]["active_in_feature_matrix"] is True
    assert report["input_status"] == "DIRECT_STATS_ACTIVE"
    assert report["source_usage"][0]["source"] == "test_source"
    assert report["production_model_touched"] is False

    print("SOURCE_FEATURE_USAGE_AUDIT=PASS")
    print("ACTIVE_POLICY_STATS", report["strict_feature_matrix"]["active_policy_stats"])
    print("EXACT_PIT_STAT_ROWS", report["database"]["exact_pit_stat_rows"])


if __name__ == "__main__":
    main()
