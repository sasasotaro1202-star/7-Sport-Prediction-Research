import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "scripts" / "pymc_pit_shadow_dataset.py"
source = path.read_text(encoding="utf-8")

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
print("PYMC_PIT_SHADOW_CONTRACT=PASS")
