#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pit_history_expansion.yml"
PRODUCTION_WORKFLOW = ROOT / ".github" / "workflows" / "v4_5_15_production.yml"


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    production = PRODUCTION_WORKFLOW.read_text(encoding="utf-8")

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

    # Canonical production recovery must prefer the PIT-enriched cache so a
    # lower-fidelity cache cannot silently mask strict historical PIT evidence.
    pit_key = "active-scope-target-db-v4-${{ matrix.sport }}-pit-"
    pre_event_key = "pre-event-target-db-v1-${{ matrix.sport }}-"
    scope_key = "scope-autofill-db-v1-${{ matrix.sport }}-"
    generic_key = "active-scope-target-db-v4-${{ matrix.sport }}-"
    production_restore_start = production.index("restore-keys: |")
    production_restore_tail = production[production_restore_start:production_restore_start + 600]
    restore_lines = [line.strip() for line in production_restore_tail.splitlines() if line.strip()]
    pit_pos = restore_lines.index(pit_key)
    pre_event_pos = restore_lines.index(pre_event_key)
    scope_pos = restore_lines.index(scope_key)
    generic_pos = restore_lines.index(generic_key)
    assert pit_pos < pre_event_pos
    assert pit_pos < scope_pos
    assert scope_pos < generic_pos

    print("PIT_CACHE_NAMESPACE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
