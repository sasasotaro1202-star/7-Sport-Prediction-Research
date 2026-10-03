#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/v4_5_15_production.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")

    required_nonblocking = {
        "dual_learning": "continue-on-error: true",
        "competition_oos": "continue-on-error: true",
        "competition_routes": "continue-on-error: true",
        "timing_routes": "continue-on-error: true",
        "release_gate": "continue-on-error: true",
        "experience_score": "continue-on-error: true",
        "experience_learning": "continue-on-error: true",
        "experience_bridge": "continue-on-error: true",
    }
    for step_id, contract in required_nonblocking.items():
        assert f"id: {step_id}" in text, f"missing step id: {step_id}"
        start = text.index(f"id: {step_id}")
        block = text[start:start + 700]
        assert contract in block, f"missing nonblocking contract: {step_id}"

    def step_block(step_name: str) -> str:
        marker = f"- name: {step_name}"
        start = text.index(marker)
        tail = text[start + len(marker):]
        next_marker = tail.find("\n      - name:")
        end = start + len(marker) + (next_marker if next_marker >= 0 else len(tail))
        return text[start:end]

    pit_block = step_block("Strict PIT replay")
    assert "continue-on-error: true" not in pit_block

    audit_block = step_block("Independent leakage audit after model generation")
    assert "continue-on-error: true" not in audit_block

    persist_start = text.index("- name: Persist safe outputs")
    persist_block = text[persist_start:persist_start + 450]
    assert "if: always()" in persist_block

    final_start = text.index("- name: Final production failure verdict")
    final_block = text[final_start:]
    assert "if: always()" in final_block
    assert "PRODUCTION_FINAL_VERDICT=FAILED_EXPLICIT_PARTIAL" in final_block
    assert "exit 1" in final_block

    recovery = (ROOT / ".github/workflows/production_failure_recovery.yml").read_text(encoding="utf-8")
    assert "contents: write" in recovery
    assert "group: production-failure-memory-writer" in recovery
    assert "record-failure-memory:" in recovery
    assert "results/failure_memory.jsonl" in recovery
    assert "needs: record-failure-memory" in recovery
    assert "run_attempt < 2" in recovery
    assert "actions/upload-artifact@v4" in recovery
    assert "git add results/failure_memory.jsonl" in recovery
    assert "git push origin HEAD:main" in recovery
    assert "Production Invariants" not in recovery
    assert "Production Safety Audit" not in recovery
    assert "\\${{ " not in recovery
    retry_start = recovery.index("  retry-transient-failure:")
    retry_block = recovery[retry_start:]
    assert retry_block.count("\n    if: >-") == 1
    assert "needs: record-failure-memory" in retry_block
    assert "always() &&" in retry_block

    print("PRODUCTION_SAFE_CONTINUATION_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())