#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/production_failure_recovery.yml"
PRODUCTION = ROOT / ".github/workflows/v4_5_15_production.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    production = PRODUCTION.read_text(encoding="utf-8")

    assert "contents: write" in text
    assert "actions: read" in text
    assert "group: production-failure-memory-writer" in text
    assert "cancel-in-progress: false" in text
    assert "record-failure-memory:" in text
    assert "results/failure_memory.jsonl" in text
    assert "Capture failed-run log" in text
    assert "source-run.log" in text
    assert "actions/upload-artifact@v4" in text
    assert "retention-days: 14" in text
    assert "retry-transient-failure:" in text
    assert "needs: record-failure-memory" in text
    assert "always() &&" in text
    assert "run_attempt < 2" in text
    assert "gh run rerun" in text
    assert "gh workflow run" in text

    # No hidden failure bypass.
    assert "|| true" not in text
    assert "continue-on-error: true" not in text

    # The heavy production workflow is schedule/dispatch driven, so committing
    # failure memory to main must not recursively launch another heavy run.
    assert "
  push:" not in production

    print("PRODUCTION_FAILURE_MEMORY_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
