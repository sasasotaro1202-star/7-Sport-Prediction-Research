import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "scripts" / "research_poc_pymc.py"
source = POC.read_text(encoding="utf-8")
ast.parse(source)
assert 'pymc-devs/pymc' in source
assert 'RESEARCH_ONLY_UNVERIFIED_PRODUCTION_EVIDENCE' in source
assert 'chronological_split' in source
assert 'future_feature_leakage' in source
assert 'production_dependency_added' in source
assert 'frozen holdout' in source
assert 'random split' not in source.lower()
assert 'random k-fold' not in source.lower()
print("PYMC_POC_CONTRACT=PASS")
