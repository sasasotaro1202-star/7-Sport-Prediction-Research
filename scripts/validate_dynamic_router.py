from __future__ import annotations
import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
path = ROOT / "src/dynamic_model_router.py"
tree = ast.parse(path.read_text(encoding="utf-8"))
assert not any(
    isinstance(n, ast.ImportFrom) and n.module == "src.dynamic_model_router"
    for n in ast.walk(tree)
), "self-import detected"

mod = importlib.import_module("src.dynamic_model_router")
required = ("DynamicModelRouter", "evaluate_router", "fit_final_router")
missing = [name for name in required if not hasattr(mod, name)]
assert not missing, f"missing public API: {missing}"

print("dynamic router syntax/import/API validation OK")
