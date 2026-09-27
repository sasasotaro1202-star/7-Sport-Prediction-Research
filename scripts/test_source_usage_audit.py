from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from src.storage.db_v45 import SCHEMA, _migrate
from src.source_usage_audit import audit


def _insert_event(con, eid, when):
    con.execute(
        "INSERT INTO event(event_id,sport,competition_id,event_time_utc,status,quality_status) VALUES(?,?,?,?,?,?)",
        (eid, "basketball", "test", when, "scheduled", "VERIFIED"),
    )
    for side, pid in (("A", f"{eid}-a"), ("B", f"{eid}-b")):
        con.execute(
            """
            INSERT INTO participant(
                participant_id,sport,participant_type,canonical_name,
                first_seen_at,last_seen_at
            ) VALUES(?,?,?,?,?,?)
            """,
            (pid, "basketball", "player", pid, when, when),
        )
        con.execute(
            """
            INSERT INTO event_participant(
                event_id,participant_id,side,source,source_url,
                effective_at_utc,quality_status
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                eid, pid, side, "espn",
                "https://site.api.espn.com/x",
                when, "EXACT",
            ),
        )


def make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    _migrate(con)

    _insert_event(con, "e1", "2026-09-20T10:00:00+00:00")
    _insert_event(con, "e2", "2026-09-22T10:00:00+00:00")

    for eid, outcome in (("e1", "A"), ("e2", "B")):
        con.execute(
            """
            INSERT INTO event_outcome(
                event_id,sport,outcome,score_a,score_b,outcome_status,
                source,source_url,observed_at_utc,quality_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                eid, "basketball", outcome, 100, 90, "VERIFIED",
                "espn", "https://site.api.espn.com/x",
                "2026-09-20T12:00:00+00:00" if eid == "e1" else "2026-09-22T12:00:00+00:00",
                "EXACT",
            ),
        )

    con.execute(
        """
        INSERT INTO source_snapshot(
            snapshot_id,sport,source,source_url,retrieved_at_utc,
            source_available_at_utc,event_time_utc,content_hash,payload_path,
            parser_version,availability_status,provenance_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "s1", "basketball", "espn", "https://site.api.espn.com/x",
            "2026-09-20T08:00:00+00:00",
            "2026-09-20T08:00:00+00:00",
            "2026-09-20T10:00:00+00:00",
            "hash-e1", "raw/e1.json", "test", "EXACT", "{}",
        ),
    )
    for pid, value in (("e1-a", 100.0), ("e1-b", 90.0)):
        con.execute(
            """
            INSERT INTO match_stats(
                stat_id,event_id,participant_id,sport,observed_at_utc,
                effective_at_utc,stat_name,value_num,source,source_url,
                quality_status,confidence
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"{pid}-points", "e1", pid, "basketball",
                "2026-09-20T08:30:00+00:00",
                "2026-09-20T08:30:00+00:00",
                "points", value, "espn",
                "https://site.api.espn.com/x", "EXACT", 1.0,
            ),
        )

    con.commit()
    con.close()


def make_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "evidence": {
                    "espn_public": {
                        "status": "research_candidate",
                        "references": ["https://github.com/sejaldua/espn-api"],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def make_policy(path: Path) -> None:
    path.write_text(
        "POLICY={'basketball':('points','rebounds'),'boxing':()}\n",
        encoding="utf-8",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db = root / "x.sqlite"
        registry = root / "registry.json"
        policy = root / "policy.py"
        make_db(db)
        make_registry(registry)
        make_policy(policy)

        result = audit(
            "basketball",
            db_path=db,
            registry_path=registry,
            policy_path=policy,
            shadow_path=root / "missing-shadow.json",
        )

        assert result["database"]["events"] == 2
        assert result["database"]["verified_outcomes"] == 2
        assert result["database"]["exact_snapshots"] == 1
        assert len(result["database"]["active_pit_features"]) == 1
        assert result["database"]["active_pit_features"][0]["stat_name"] == "points"
        assert result["database"]["active_pit_features"][0]["strict_pit_active"] is True

        matrix = result["database"]["feature_matrix_usage"]
        assert matrix["build_rows"] >= 1
        assert matrix["feature_count"] > 0
        assert "points" in matrix["active_policy_stats"]
        assert matrix["stat_feature_usage"]["points"]["active_in_feature_matrix"] is True
        assert result["shadow"]["manifest_present"] is False

        # An observed stat outside POLICY must stay data-only and never become
        # an active model input through this audit path.
        policy.write_text(
            "POLICY={'basketball':('rebounds',),'boxing':()}\n",
            encoding="utf-8",
        )
        result2 = audit(
            "basketball",
            db_path=db,
            registry_path=registry,
            policy_path=policy,
            shadow_path=root / "missing-shadow.json",
        )
        assert len(result2["database"]["active_pit_features"]) == 0
        assert result2["database"]["feature_matrix_usage"]["active_policy_stats"] == []
        assert result2["database"]["feature_usage"][0]["policy_allows_stat"] is False

    print("SOURCE_USAGE_AUDIT=PASS")
    print("SOURCE_USAGE_PIT_GUARD=PASS")
    print("SOURCE_USAGE_FEATURE_MATRIX=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
