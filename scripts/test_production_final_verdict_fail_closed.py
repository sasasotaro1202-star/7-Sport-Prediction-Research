#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/v4_5_15_production.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "- name: Final production failure verdict"
    assert marker in text

    start = text.index(marker)
    block = text[start:]
    assert "if: always()" in block
    assert "JOB_STATUS: ${{ job.status }}" in block
    assert 'case "$JOB_STATUS" in' in block
    assert "failure)" in block
    assert "cancelled)" in block
    assert "failed=1" in block

    # The final PASS must occur only after the job-status guard and failure gate.
    status_guard = block.index('case "$JOB_STATUS" in')
    pass_line = block.index('echo "PRODUCTION_FINAL_VERDICT=PASS"')
    fail_guard = block.index('if [ "$failed" -ne 0 ]; then')
    assert status_guard < fail_guard < pass_line

    # Unknown step outcomes must fail closed rather than silently becoming PASS.
    assert "UNKNOWN_RESULT_" in block
    assert "FINAL_JOB_STATUS=UNKNOWN_" in block

    print("PRODUCTION_FINAL_VERDICT_FAIL_CLOSED=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
