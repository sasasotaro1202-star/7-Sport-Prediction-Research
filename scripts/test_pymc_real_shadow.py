from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
src=(ROOT/"scripts"/"research_pymc_real_shadow.py").read_text(encoding="utf-8")
workflow=(ROOT/".github"/"workflows"/"prediction_core_pymc_real_shadow.yml").read_text(encoding="utf-8")
pit=(ROOT/"src"/"pit_replay_builder.py").read_text(encoding="utf-8")
ast.parse(src)
ast.parse(pit)
for token in ("SPORT_SINGLE","chronological","prediction_cutoff_before_outcome","production_dependency","automatic_promotion","SHADOW_PERFORMANCE_OBSERVED","POLICY[sport]","oov_team"):
    assert token in src
assert "train_test_split" not in src
assert "KFold" not in src
assert "random_split" not in src.lower()
print("PYMC_REAL_SHADOW_CONTRACT=PASS")

for sport in ("basketball", "volleyball", "ufc", "rizin", "valorant"):
    assert sport in workflow
assert "--force" in workflow
assert "--require-current-replay" in workflow
assert "from src.research_policy import POLICY" in pit
assert "from src.research_cycle_v4 import POLICY" not in pit
print("PYMC_REAL_SHADOW_PIT_PROVENANCE_CONTRACT=PASS")

assert "symmetry_max_abs_error" in src
assert "PYMC_SYMMETRY_FAIL" in src

assert "fit_logistic_baseline" in src
assert "matched_feature_logistic_logloss" in src
assert "pymc_vs_matched_logistic_logloss_delta" in src
