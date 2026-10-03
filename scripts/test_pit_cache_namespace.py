#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pit_history_expansion.yml"


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "  push:" not in workflow
    assert "cron: '47 0,9,18 * * *'" in workflow
    assert "Determine PIT expansion execution mode" in workflow

    assert "Require non-empty PIT seed cache" in workflow
    assert "PIT_SEED_CACHE_MISSING:" in workflow
    assert "PIT_SEED_CACHE_EMPTY:" in workflow
    assert "PIT_SEED_CACHE=PASS" in workflow

    required = (
        "active-scope-target-db-v4-${{ matrix.sport }}-pit-",
        "active-scope-target-db-v4-${{ matrix.sport }}-",
        "key: active-scope-target-db-v4-${{ matrix.sport }}-pit-${{ github.run_id }}",
    )
    for marker in required:
        assert marker in workflow, marker

    save_key = "key: active-scope-target-db-v4-${{ matrix.sport }}-pit-${{ github.run_id }}"
    assert workflow.count(save_key) == 1
    restore_start = workflow.index("restore-keys: |")
    restore_tail = workflow[restore_start:restore_start + 500]
    assert "active-scope-target-db-v4-${{ matrix.sport }}-pit-" in restore_tail

    print("PIT_CACHE_NAMESPACE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
