from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from src.source_usage_audit import audit


def make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE event(event_id TEXT PRIMARY KEY,sport TEXT,event_time_utc TEXT);
        CREATE TABLE event_outcome(event_id TEXT PRIMARY KEY,sport TEXT,outcome_status TEXT);
        CREATE TABLE source_snapshot(
          snapshot_id TEXT PRIMARY KEY,sport TEXT,source TEXT,source_url TEXT,
          source_available_at_utc TEXT,event_time_utc TEXT,availability_status TEXT
        );
        CREATE TABLE match_stats(
          stat_id TEXT PRIMARY KEY,event_id TEXT,participant_id TEXT,sport TEXT,
          stat_name TEXT,value_num REAL,source TEXT,source_url TEXT,effective_at_utc TEXT
        );
        """
    )
    con.execute("INSERT INTO event VALUES (?,?,?)", ("e1","basketball","2026-09-20T10:00:00+00:00"))
    con.execute("INSERT INTO event_outcome VALUES (?,?,?)", ("e1","basketball","VERIFIED"))
    con.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?)",
        ("s1","basketball","espn","https://site.api.espn.com/x","2026-09-20T08:00:00+00:00","2026-09-20T10:00:00+00:00","EXACT"),
    )
    con.execute(
        "INSERT INTO match_stats VALUES (?,?,?,?,?,?,?,?,?)",
        ("m1","e1","p1","basketball","points",100.0,"espn","https://site.api.espn.com/x","2026-09-20T08:00:00+00:00"),
    )
    con.commit()
    con.close()


def make_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {"evidence":{"espn_public":{"status":"research_candidate","references":["https://github.com/sejaldua/espn-api"]}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def make_policy(path: Path) -> None:
    path.write_text("POLICY={'basketball':('points','rebounds'),'boxing':()}\n", encoding="utf-8")


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
        assert result["database"]["events"] == 1
        assert result["database"]["verified_outcomes"] == 1
        assert result["database"]["exact_snapshots"] == 1
        assert len(result["database"]["active_pit_features"]) == 1
        assert result["database"]["active_pit_features"][0]["stat_name"] == "points"
        assert result["database"]["active_pit_features"][0]["strict_pit_active"] is True
        assert result["shadow"]["manifest_present"] is False

        # A stat outside POLICY is observed in DB but must never become an active model feature.
        policy.write_text("POLICY={'basketball':('rebounds',),'boxing':()}\n", encoding="utf-8")
        result2 = audit(
            "basketball",
            db_path=db,
            registry_path=registry,
            policy_path=policy,
            shadow_path=root / "missing-shadow.json",
        )
        assert len(result2["database"]["active_pit_features"]) == 0
        assert result2["database"]["feature_usage"][0]["policy_allows_stat"] is False

    print("SOURCE_USAGE_AUDIT=PASS")
    print("SOURCE_USAGE_PIT_GUARD=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
