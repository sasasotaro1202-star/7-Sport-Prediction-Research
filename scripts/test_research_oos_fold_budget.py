from src.research_cycle_strict import _bounded_oos_fold_params

cases = {
    200: 6,
    1000: 6,
    5000: 6,
    8000: 8,
    20000: 8,
}

for sel, expected_folds in cases.items():
    folds, step = _bounded_oos_fold_params(sel)
    assert folds == expected_folds, (sel, folds)
    assert step >= 10, (sel, step)

assert _bounded_oos_fold_params(0) == (6, 10)
assert _bounded_oos_fold_params(120)[0] == 6
assert _bounded_oos_fold_params(12000)[0] == 8

print("bounded OOS fold schedule: PASS")
