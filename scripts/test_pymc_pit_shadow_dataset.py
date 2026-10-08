from pathlib import Path
import ast
import os
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "scripts" / "pymc_pit_shadow_dataset.py").read_text(encoding="utf-8")
workflow = (ROOT / ".github" / "workflows" / "prediction_core_pymc_pit_shadow.yml").read_text(encoding="utf-8")
pit = (ROOT / "src" / "pit_replay_builder.py").read_text(encoding="utf-8")
cycle = (ROOT / "src" / "research_cycle_v4.py").read_text(encoding="utf-8")

ast.parse(src)
ast.parse(pit)
ast.parse(cycle)

for token in ("--sport", "SPORT_SINGLE", "source_available_at_utc", "PIT_SOURCE_NOT_EXACT", "FUTURE_SOURCE_FAIL", "FEATURE_LEAKAGE_FAIL", "automatic_promotion", "require_current_replay", "REPLAY_PROVENANCE_FAIL", "current_replay_provenance_verified", "diagnostics", "exclude_frozen_holdout"):
    assert token in src
assert "retrieved_at_utc" not in src
assert "from src.research_cycle_v4 import POLICY" not in pit
assert "from src.research_policy import POLICY" in pit
assert "from src.research_policy import POLICY, SPORTS" in cycle
assert "import os" in pit
assert "REPLAY_GIT_SHA" in pit
assert "INSERT OR REPLACE INTO pit_replay" in pit
assert "FEATURE_VERSION,'strict-pit',REPLAY_GIT_SHA, None, fingerprint" in pit

for sport in ("basketball", "volleyball", "ufc", "rizin", "valorant"):
    assert sport in workflow

for token in ("active-scope-target-db-v4-${{ matrix.sport }}-pit-", "nine-sport-research-db-v4-${{ matrix.sport }}-", "nine-sport-target-db-v4-${{ matrix.sport }}-pit-", "cache-matched-key", "pit_replay_builder", "--force", "--require-current-replay", "PIT_SOURCE_CACHE_MISSING", "INSUFFICIENT_PIT_EVIDENCE", "BLOCKED_SOURCE_COVERAGE", "MERGED_PIT_DB_SCOPE_CONTAMINATION", "PIT_DATASET_ONLY_NO_MODEL_PERFORMANCE_EVIDENCE"):
    assert token in workflow
assert "src/research_policy.py" in workflow
assert "src/pit_replay_builder.py" in workflow
assert "needs.collect-pit-source.result != 'success'" in workflow
assert "Install minimal PIT replay runtime" not in workflow

from scripts.pymc_pit_shadow_dataset import build

with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "fixture.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE event (event_id TEXT PRIMARY KEY, sport TEXT, competition_id TEXT, event_time_utc TEXT);
    CREATE TABLE event_participant (event_id TEXT, side TEXT, participant_id TEXT, team_id TEXT);
    CREATE TABLE event_outcome (event_id TEXT PRIMARY KEY, sport TEXT, outcome TEXT, outcome_status TEXT);
    CREATE TABLE pit_replay (replay_id TEXT PRIMARY KEY, event_id TEXT, prediction_cutoff_at_utc TEXT, replay_status TEXT, leakage_status TEXT, dataset_hash TEXT, git_commit_sha TEXT);
    CREATE TABLE pit_feature_snapshot (snapshot_id TEXT PRIMARY KEY, replay_id TEXT, event_id TEXT, sport TEXT, cutoff_at_utc TEXT, feature_name TEXT, value_num REAL, value_text TEXT, source_observation_ids TEXT, leakage_status TEXT);
    CREATE TABLE source_snapshot (snapshot_id TEXT PRIMARY KEY, sport TEXT, availability_status TEXT, source_available_at_utc TEXT, retrieved_at_utc TEXT);
    """)
    con.execute("INSERT INTO event VALUES (?,?,?,?)", ("e1","basketball","B.LEAGUE","2026-01-01T12:00:00+00:00"))
    con.executemany("INSERT INTO event_participant VALUES (?,?,?,?)", [("e1","A","pa","ta"),("e1","B","pb","tb")])
    con.execute("INSERT INTO event_outcome VALUES (?,?,?,?)", ("e1","basketball","A","VERIFIED"))
    con.execute("INSERT INTO pit_replay VALUES (?,?,?,?,?,?,?)", ("r1","e1","2026-01-01T11:00:00+00:00","REPLAYABLE","CLEAN","d1","test-sha"))
    con.execute("INSERT INTO pit_feature_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)", ("f1","r1","e1","basketball","2026-01-01T11:00:00+00:00","A__points__mean",100.0,None,'["s1"]',"CLEAN"))
    con.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?)", ("s1","basketball","EXACT","2026-01-01T10:30:00+00:00","2026-10-08T00:00:00+00:00"))
    con.commit(); con.close()

    previous = os.environ.get("GITHUB_SHA")
    os.environ["GITHUB_SHA"] = "test-sha"
    try:
        ok = build(db, sport="basketball", require_current_replay=True)
        assert ok["status"] == "READY"
        assert ok["row_count"] == 1
        assert ok["current_replay_provenance_verified"] is True
        assert ok["diagnostics"]["replayable_rows"] == 1

        con = sqlite3.connect(db)
        con.execute("UPDATE source_snapshot SET source_available_at_utc=? WHERE snapshot_id='s1'", ("2026-01-01T11:30:00+00:00",))
        con.commit(); con.close()
        try:
            build(db, sport="basketball", require_current_replay=True)
        except RuntimeError as exc:
            assert str(exc).startswith("FUTURE_SOURCE_FAIL:")
        else:
            raise AssertionError("future source was accepted")

        con = sqlite3.connect(db)
        con.execute("UPDATE source_snapshot SET source_available_at_utc=? WHERE snapshot_id='s1'", ("2026-01-01T10:30:00+00:00",))
        con.execute("UPDATE pit_replay SET git_commit_sha='old-sha' WHERE replay_id='r1'")
        con.commit(); con.close()
        try:
            build(db, sport="basketball", require_current_replay=True)
        except RuntimeError as exc:
            assert str(exc).startswith("REPLAY_PROVENANCE_FAIL:")
        else:
            raise AssertionError("stale replay provenance was accepted")
    finally:
        if previous is None: os.environ.pop('GITHUB_SHA', None)
        else: os.environ['GITHUB_SHA'] = previous

print("PYMC_PIT_SHADOW_CONTRACT=PASS")
print("PYMC_PIT_SHADOW_EXECUTABLE_FIXTURE_CONTRACT=PASS")

assert "--exclude-frozen-holdout" in workflow
