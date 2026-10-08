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
