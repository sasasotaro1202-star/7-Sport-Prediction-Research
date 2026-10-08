import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "scripts" / "pymc_pit_shadow_dataset.py"
workflow = ROOT / ".github" / "workflows" / "prediction_core_pymc_pit_shadow.yml"
source = path.read_text(encoding="utf-8")
workflow_source = workflow.read_text(encoding="utf-8")
pit_replay_source = (ROOT / "src" / "pit_replay_builder.py").read_text(encoding="utf-8")
research_cycle_source = (ROOT / "src" / "research_cycle_v4.py").read_text(encoding="utf-8")

ast.parse(source)

for token in (
    "production_dependency",
    "automatic_promotion",
    "prediction_cutoff_at_utc",
    "source_snapshot",
    "PIT_SOURCE_NOT_EXACT",
    "FUTURE_SOURCE_FAIL",
    "FEATURE_LEAKAGE_FAIL",
):
    assert token in source

assert "requirements.txt" not in source

for sport in ("basketball", "volleyball", "ufc", "rizin", "valorant"):
    assert sport in workflow_source, f"missing active sport in shadow workflow: {sport}"

for token in (
    "active-scope-target-db-v4-${{ matrix.sport }}-pit-",
    "nine-sport-research-db-v4-${{ matrix.sport }}-",
    "nine-sport-target-db-v4-${{ matrix.sport }}-pit-",
    "cache-matched-key",
    "pit_replay_builder",
    "--force",
    "BLOCKED_SOURCE_COVERAGE",
    "trajectory-ready-db-v1-merged-${{ github.run_id }}",
    "production_dependency",
    "automatic_promotion",
):
    assert token in workflow_source, f"missing workflow safety token: {token}"

assert "PIT_SOURCE_CACHE_MISSING" in workflow_source
assert "INSUFFICIENT_PIT_EVIDENCE" in workflow_source
assert "Install minimal PIT replay runtime" not in workflow_source
assert "from src.research_policy import POLICY" in pit_replay_source
assert "from src.research_policy import POLICY, SPORTS" in research_cycle_source
assert "from src.research_cycle_v4 import POLICY" not in pit_replay_source
assert "pymc_pit_shadow_source_manifest.json" in workflow_source
assert "pymc_pit_shadow_execution.json" in workflow_source
assert "PIT_DATASET_ONLY_NO_MODEL_PERFORMANCE_EVIDENCE" in workflow_source
assert "needs.collect-pit-source.result != 'success'" in workflow_source
assert "MERGED_PIT_DB_SCOPE_CONTAMINATION" in workflow_source

print("PYMC_PIT_SHADOW_CONTRACT=PASS")
