import ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/"scripts/research_pymc_wfo.py").read_text(encoding="utf-8")
workflow=(ROOT/".github"/"workflows"/"prediction_core_pymc_wfo.yml").read_text(encoding="utf-8")
ast.parse(source)
for token in ("WFO_PERFORMANCE_OBSERVED","chronological","future_feature_leakage","prediction_cutoff_before_outcome","BLOCKED_INSUFFICIENT_WFO_ROWS","automatic_promotion","folds_better_than_0_5_logloss","folds_better_than_matched_logistic","matched_logistic_logloss_mean","pymc_vs_matched_logistic_logloss_delta_mean","logloss_worst","max_r_hat_across_folds"):
    assert token in source
assert "train_test_split" not in source and "KFold" not in source and "random_split" not in source.lower()
assert "--draws" in workflow and "--tune" in workflow and "active-scope-target-db-v4-${{ matrix.sport }}-pit-" in workflow and "--require-current-replay" in workflow
print("PYMC_WFO_CONTRACT=PASS")

assert "src/research_policy.py" in workflow
assert "src/pit_replay_builder.py" in workflow
assert "GITHUB_SHA: ${{ github.sha }}" in workflow

assert "github_head_sha" in source
assert "production_dependency" in source
assert "automatic_promotion" in source
