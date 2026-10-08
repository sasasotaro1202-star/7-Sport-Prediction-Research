from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
src=(ROOT/"scripts"/"research_pymc_real_shadow.py").read_text(encoding="utf-8")
ast.parse(src)
for token in ("SPORT_SINGLE","chronological","prediction_cutoff_before_outcome","production_dependency","automatic_promotion","SHADOW_PERFORMANCE_OBSERVED"):
    assert token in src
assert "train_test_split" not in src
assert "KFold" not in src
assert "random_split" not in src.lower()
print("PYMC_REAL_SHADOW_CONTRACT=PASS")
