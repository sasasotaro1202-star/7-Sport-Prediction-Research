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

    relay = ROOT / ".github/workflows/production_watchdog_event_relay.yml"
    assert not relay.exists(), "production watchdog event relay must remain absent to prevent workflow_run event storms"
    watchdog = (ROOT / ".github/workflows/production_watchdog.yml").read_text(encoding="utf-8")
    assert "Cancel stale unfinished heavy runs from old commits only when unsafe" in watchdog
    watchdog_start = watchdog.index("      - name: Cancel stale unfinished heavy runs from old commits only when unsafe")
    watchdog_end = watchdog.index("      - name: Ensure validated latest-main production is continuously scheduled", watchdog_start)
    watchdog_block = watchdog[watchdog_start:watchdog_end]
    assert 'repos/${GITHUB_REPOSITORY}/compare/${run_sha}...${main_sha}' in watchdog_block
    assert "DURABLE_ONLY" in watchdog_block
    assert "DURABLE_ONLY_HEAVY_RUN_PRESERVED" in watchdog_block
    assert "results/research/autonomous_control_plane.json" in watchdog_block
    assert "results/research/automation_health.json" in watchdog_block
    assert "results/research/research_queue.jsonl" in watchdog_block
    assert "results/research/autonomous_action_log.jsonl" in watchdog_block
    assert "results/automation_state/" in watchdog_block
    assert "results/failure_memory.jsonl" in watchdog_block
    assert "UNVERIFIABLE" in watchdog_block

    # Durable-only main commits may inherit validator evidence from the nearest
    # non-durable semantic revision; generated-output commits retain their narrow path.
    watchdog_start = watchdog.index("      - name: Ensure validated latest-main production is continuously scheduled")
    watchdog_end = watchdog.index("      - name: Backfill a missed 9-hour PIT boundary once per boundary window", watchdog_start)
    validator_block = watchdog[watchdog_start:watchdog_end]
    assert "validation_base_sha=\"$main_sha\"" in validator_block
    assert "validation_walk" in validator_block
    assert "INHERITED_VALIDATION_FROM_DURABLE_ONLY_BASE" in validator_block
    assert "inv_ok=$(printf" in validator_block
    assert "results/research/autonomous_control_plane.json" in validator_block
    assert "results/failure_memory.jsonl" in validator_block

    relay = (ROOT / ".github/workflows/production_watchdog_event_relay.yml").read_text(encoding="utf-8")
    assert "workflow_run:" in relay
    assert "if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'" in relay
    for workflow_name in ("Production Invariants", "Lightweight Regression and Safety Checks", "Production Safety Audit", "PIT History Expansion", "Autonomous Research Control Plane"):
        assert workflow_name in relay
    assert "actions: write" in relay
    assert "contents: read" in relay
    assert "group: production-watchdog-event-relay" in relay
    assert "cancel-in-progress: true" in relay
    assert "RELAY_MAIN_ADVANCED_REFRESH" in relay
    assert "AUTO_WATCHDOG_RELAY_VERIFIED" in relay
    assert "PRODUCTION_WATCHDOG_RELAY_SKIPPED" in relay
    recovery = (ROOT / ".github/workflows/production_failure_recovery.yml").read_text(encoding="utf-8")
    assert "contents: write" in recovery
    assert "group: production-failure-memory-writer" in recovery
    assert "record-failure-memory:" in recovery
    assert "branches:\n      - main" in recovery
    assert "types:\n      - completed" in recovery
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