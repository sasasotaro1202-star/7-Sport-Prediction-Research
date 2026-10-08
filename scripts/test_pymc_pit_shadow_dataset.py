from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
src=(ROOT/"scripts"/"pymc_pit_shadow_dataset.py").read_text(encoding="utf-8")
ast.parse(src)
for token in ("--sport","SPORT_SINGLE","source_available_at_utc","PIT_SOURCE_NOT_EXACT","FUTURE_SOURCE_FAIL","FEATURE_LEAKAGE_FAIL","automatic_promotion"):
    assert token in src
assert "retrieved_at_utc" not in src
print("PYMC_PIT_SHADOW_CONTRACT=PASS")

assert "require_current_replay" in src
assert "--require-current-replay" in src
assert "REPLAY_PROVENANCE_FAIL" in src

for token in ("diagnostics", "event_rows", "verified_outcomes", "replayable_rows", "clean_feature_rows", "exact_source_rows"):
    assert token in src

assert "import os" in (ROOT/"src"/"pit_replay_builder.py").read_text(encoding="utf-8")

import os
import sqlite3
import tempfile

from scripts.pymc_pit_shadow_dataset import build

with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "fixture.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE event (
        event_id TEXT PRIMARY KEY, sport TEXT, competition_id TEXT,
        event_time_utc TEXT
    );
    CREATE TABLE event_participant (
        event_id TEXT, side TEXT, participant_id TEXT, team_id TEXT
    );
    CREATE TABLE event_outcome (
        event_id TEXT PRIMARY KEY, sport TEXT, outcome TEXT,
        outcome_status TEXT
    );
    CREATE TABLE pit_replay (
        replay_id TEXT PRIMARY KEY, event_id TEXT,
        prediction_cutoff_at_utc TEXT, replay_status TEXT,
        leakage_status TEXT, dataset_hash TEXT, git_commit_sha TEXT
    );
    CREATE TABLE pit_feature_snapshot (
        snapshot_id TEXT PRIMARY KEY, replay_id TEXT, event_id TEXT,
        sport TEXT, cutoff_at_utc TEXT, feature_name TEXT,
        value_num REAL, value_text TEXT, source_observation_ids TEXT,
        leakage_status TEXT
    );
    CREATE TABLE source_snapshot (
        snapshot_id TEXT PRIMARY KEY, sport TEXT, availability_status TEXT,
        source_available_at_utc TEXT, retrieved_at_utc TEXT
    );
    """)
    con.execute(
        "INSERT INTO event(event_id,sport,competition_id,event_time_utc) VALUES (?,?,?,?)",
        ("e1","basketball","B.LEAGUE","2026-01-01T12:00:00+00:00")
    )
    con.executemany(
        "INSERT INTO event_participant(event_id,side,participant_id,team_id) VALUES (?,?,?,?)",
        [("e1","A","pa","ta"),("e1","B","pb","tb")]
    )
    con.execute(
        "INSERT INTO event_outcome(event_id,sport,outcome,outcome_status) VALUES (?,?,?,?)",
        ("e1","basketball","A","VERIFIED")
    )
    con.execute(
        "INSERT INTO pit_replay VALUES (?,?,?,?,?,?,?)",
        ("r1","e1","2026-01-01T11:00:00+00:00","REPLAYABLE","CLEAN","d1","test-sha")
    )
    con.execute(
        "INSERT INTO pit_feature_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("f1","r1","e1","basketball","2026-01-01T11:00:00+00:00",
         "A__points__mean",100.0,None,'["s1"]',"CLEAN")
    )
    con.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?)",
        ("s1","basketball","EXACT","2026-01-01T10:30:00+00:00","2026-10-08T00:00:00+00:00")
    )
    con.commit()
    con.close()

    old_sha = os.environ.get("GITHUB_SHA")
    os.environ["GITHUB_SHA"] = "test-sha"
    try:
        ready = build(db, sport="basketball", require_current_replay=True)
        assert ready["status"] == "READY"
        assert ready["row_count"] == 1
        assert ready["current_replay_provenance_verified"] is True
        assert ready["diagnostics"]["replayable_rows"] == 1

        con = sqlite3.connect(db)
        con.execute(
            "UPDATE source_snapshot SET source_available_at_utc=? WHERE snapshot_id='s1'",
            ("2026-01-01T11:30:00+00:00",)
        )
        con.commit()
        con.close()
        try:
            build(db, sport="basketball", require_current_replay=True)
        except RuntimeError as exc:
            assert str(exc).startswith("FUTURE_SOURCE_FAIL:")
        else:
            raise AssertionError("future source was not rejected")

        con = sqlite3.connect(db)
        con.execute(
            "UPDATE source_snapshot SET source_available_at_utc=? WHERE snapshot_id='s1'",
            ("2026-01-01T10:30:00+00:00",)
        )
        con.execute("UPDATE pit_replay SET git_commit_sha='old-sha' WHERE replay_id='r1'")
        con.commit()
        con.close()
        try:
            build(db, sport="basketball", require_current_replay=True)
        except RuntimeError as exc:
            assert str(exc).startswith("REPLAY_PROVENANCE_FAIL:")
        else:
            raise AssertionError("replay SHA mismatch was not rejected")
    finally:
        if old_sha is None:
            os.environ.pop("GITHUB_SHA", None)
        else:
            os.environ["GITHUB_SHA"] = old_sha

print("PYMC_PIT_SHADOW_EXECUTABLE_FIXTURE_CONTRACT=PASS")


# Executable fixture contract: validate current replay provenance and future-source fail-closed.
import os
import sqlite3
import tempfile

from scripts.pymc_pit_shadow_dataset import build

with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "fixture.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE event (
        event_id TEXT PRIMARY KEY, sport TEXT, competition_id TEXT,
        event_time_utc TEXT
    );
    CREATE TABLE event_participant (
        event_id TEXT, side TEXT, participant_id TEXT, team_id TEXT
    );
    CREATE TABLE event_outcome (
        event_id TEXT PRIMARY KEY, sport TEXT, outcome TEXT,
        outcome_status TEXT
    );
    CREATE TABLE pit_replay (
        replay_id TEXT PRIMARY KEY, event_id TEXT,
        prediction_cutoff_at_utc TEXT, replay_status TEXT,
        leakage_status TEXT, dataset_hash TEXT, git_commit_sha TEXT
    );
    CREATE TABLE pit_feature_snapshot (
        snapshot_id TEXT PRIMARY KEY, replay_id TEXT, event_id TEXT,
        sport TEXT, cutoff_at_utc TEXT, feature_name TEXT,
        value_num REAL, value_text TEXT, source_observation_ids TEXT,
        leakage_status TEXT
    );
    CREATE TABLE source_snapshot (
        snapshot_id TEXT PRIMARY KEY, sport TEXT, availability_status TEXT,
        source_available_at_utc TEXT, retrieved_at_utc TEXT
    );
    """)
    con.execute(
        "INSERT INTO event(event_id,sport,competition_id,event_time_utc) VALUES (?,?,?,?)",
        ("e1", "basketball", "B.LEAGUE", "2026-01-01T12:00:00+00:00"),
    )
    con.executemany(
        "INSERT INTO event_participant(event_id,side,participant_id,team_id) VALUES (?,?,?,?)",
        [("e1", "A", "pa", "ta"), ("e1", "B", "pb", "tb")],
    )
    con.execute(
        "INSERT INTO event_outcome(event_id,sport,outcome,outcome_status) VALUES (?,?,?,?)",
        ("e1", "basketball", "A", "VERIFIED"),
    )
    con.execute(
        "INSERT INTO pit_replay VALUES (?,?,?,?,?,?,?)",
        ("r1", "e1", "2026-01-01T11:00:00+00:00", "REPLAYABLE", "CLEAN", "d1", "test-sha"),
    )
    con.execute(
        "INSERT INTO pit_feature_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "f1", "r1", "e1", "basketball", "2026-01-01T11:00:00+00:00",
            "A__points__mean", 100.0, None, '["s1"]', "CLEAN",
        ),
    )
    con.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?)",
        (
            "s1", "basketball", "EXACT",
            "2026-01-01T10:30:00+00:00",
            "2026-10-08T00:00:00+00:00",
        ),
    )
    con.commit()
    con.close()

    old_sha = os.environ.get("GITHUB_SHA")
    os.environ["GITHUB_SHA"] = "test-sha"
    try:
        ready = build(db, sport="basketball", require_current_replay=True)
        assert ready["status"] == "READY"
        assert ready["row_count"] == 1
        assert ready["current_replay_provenance_verified"] is True
        assert ready["diagnostics"]["replayable_rows"] == 1

        con = sqlite3.connect(db)
        con.execute(
            "UPDATE source_snapshot SET source_available_at_utc=? WHERE snapshot_id='s1'",
            ("2026-01-01T11:30:00+00:00",),
        )
        con.commit()
        con.close()
        try:
            build(db, sport="basketball", require_current_replay=True)
        except RuntimeError as exc:
            assert str(exc).startswith("FUTURE_SOURCE_FAIL:")
        else:
            raise AssertionError("future source was not rejected")

        con = sqlite3.connect(db)
        con.execute(
            "UPDATE source_snapshot SET source_available_at_utc=? WHERE snapshot_id='s1'",
            ("2026-01-01T10:30:00+00:00",),
        )
        con.execute(
            "UPDATE pit_replay SET git_commit_sha='old-sha' WHERE replay_id='r1'"
        )
        con.commit()
        con.close()
        try:
            build(db, sport="basketball", require_current_replay=True)
        except RuntimeError as exc:
            assert str(exc).startswith("REPLAY_PROVENANCE_FAIL:")
        else:
            raise AssertionError("replay SHA mismatch was not rejected")
    finally:
        if old_sha is None:
            os.environ.pop("GITHUB_SHA", None)
        else:
            os.environ["GITHUB_SHA"] = old_sha

print("PYMC_PIT_SHADOW_EXECUTABLE_FIXTURE_CONTRACT=PASS")
