from __future__ import annotations

import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/"scripts/research_pymc_real_shadow.py"
src=MODEL.read_text(encoding="utf-8")
ast.parse(src)

for token in (
    "dataset_scope",
    "chronological_split",
    "prediction_cutoff_before_outcome",
    "future_source_check",
    "missing_indicators_included",
    "fit_scaler_on_train_only",
    "frozen holdout",
    "automatic_promotion",
    "production_dependency",
    "SHADOW_PERFORMANCE_OBSERVED",
):
    assert token in src, token

assert "train_test_split" not in src
assert "KFold" not in src
assert "random_split" not in src.lower()
assert "0.5" in src
print("PYMC_REAL_SHADOW_CONTRACT=PASS")
