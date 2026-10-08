from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "reliable_main_push.py"


def main() -> None:
    source = HELPER.read_text(encoding="utf-8")
    tree = ast.parse(source)

    found_push = False
    found_parent_guard = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "verify_local_parent":
            found_parent_guard = True
        if isinstance(node.func, ast.Name) and node.func.id == "run_capture":
            if not node.args or not isinstance(node.args[0], ast.List):
                continue
            values = [
                elt.value
                for elt in node.args[0].elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
            if len(values) == 4 and values[:3] == ["git", "push", "origin"] and values[3].endswith(":main"):
                found_push = True

    assert found_push
    assert found_parent_guard
    assert "RELIABLE_PUSH_STALE_MAIN" in source
    print("RELIABLE_MAIN_PUSH_CONTRACT=PASS")


if __name__ == "__main__":
    main()
