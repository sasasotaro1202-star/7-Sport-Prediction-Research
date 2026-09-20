from __future__ import annotations
import ast, pathlib
p=pathlib.Path("src/dynamic_model_router.py")
m=ast.parse(p.read_text())
assert not any(isinstance(n, ast.ImportFrom) and n.module=="src.dynamic_model_router" for n in ast.walk(m))
print("dynamic_router syntax OK")
