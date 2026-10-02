from pathlib import Path

def test_strict_oos_uses_defined_uncertainty_holdout_name():
    source = Path("src/research_cycle_strict.py").read_text(encoding="utf-8")
    assert "'uncertainty_hold': uncertainty_hold" not in source
    assert "'uncertainty_holdout': uncertainty_holdout" in source
