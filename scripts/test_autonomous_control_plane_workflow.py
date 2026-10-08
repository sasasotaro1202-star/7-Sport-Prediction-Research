from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/autonomous_control_plane.yml"
INSTRUCTIONS = ROOT / "PROJECT_INSTRUCTIONS.md"
SOURCE = ROOT / "PROJECT_SOURCE.md"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    dispatch_marker = "      - name: Dispatch at most one allowlisted autonomous workflow"
    persist_marker = "      - name: Persist deterministic control-plane state"
    final_marker = "      - name: Final control-plane status"

    dispatch = text.index(dispatch_marker)
    persist = text.index(persist_marker)
    final = text.index(final_marker)

    assert persist < dispatch < final, "dispatch must occur only after persistence"

    assert "workflow_run:" not in text, "control plane must not create a run for every completed workflow"
    assert "\n  workflow_run:" not in text
    assert "event.workflow_run." not in text, "control plane must not depend on completed-workflow event payloads"
    assert "push:" in text
    assert text.count("  push:") == 1
    assert "'src/**'" in text
    assert "'scripts/**'" in text
    assert "'.github/workflows/**'" in text
    assert "'config/**'" in text
    assert "github.event.workflow_run.conclusion" not in text
    assert "CONTROL_PLANE_EVENT_WORKFLOW" not in text
    assert "CONTROL_PLANE_EVENT_CONCLUSION" not in text
    assert "CONTROL_PLANE_EVENT_HEAD_SHA" not in text
    assert "CONTROL_PLANE_EVENT_ANCESTOR_OF_MAIN" not in text

    reconcile_markers = (
        "      - name: Resolve current main and verify execution SHA",
        "      - name: Resolve current main for control-plane execution",
    )
    reconcile_marker = next((m for m in reconcile_markers if m in text), None)
    assert reconcile_marker is not None, "current-main reconciliation step is required"
    reconcile = text.index(reconcile_marker)
    regression_marker = "      - name: Run control-plane regression"
    regression = text.index(regression_marker)
    assert reconcile < regression, "current-main resolution must precede control-plane execution"
    reconcile_block = text[reconcile:regression]
    assert "github.event_name" in reconcile_block
    assert "git fetch origin main --depth=1" in reconcile_block
    assert 'git checkout --detach "$remote_sha"' in reconcile_block
    assert 'if [ "${{ github.event_name }}" = "push" ]; then' in reconcile_block
    assert 'else' in reconcile_block
    assert 'test "$remote_sha" = "${{ github.sha }}"' in reconcile_block

    persist_block = text[persist:dispatch]
    dispatch_block = text[dispatch:final]

    assert "cancel-in-progress: true" in text
    assert "idempotent and safely restartable" in text
    assert "id: persist" in persist_block
    assert 'git ls-files --error-unmatch -- "$state_path"' in persist_block
    assert 'CONTROL_PLANE_STATE_NOT_TRACKED_OR_MISSING path=$state_path' in persist_block
    assert 'echo "persist_ok=true" >> "$GITHUB_OUTPUT"' in persist_block
    assert 'echo "main_sha=' in persist_block
    assert 'write_needed="$(python -c' in persist_block
    assert 'queue_added="$(python -c' in persist_block
    assert 'CONTROL_PLANE_SEMANTIC_CHANGE write_needed=$write_needed queue_added=$queue_added' in persist_block
    assert 'if [ "$write_needed" = true ] || [ "$queue_added" = true ]; then' in persist_block
    assert 'remote_sha="$(gh api "repos/${{ github.repository }}/git/ref/heads/main"' in persist_block
    assert '["timeout", "10s", *cmd]' in text
    assert "COMMAND_TIMEOUT" in text

    assert "steps.control.outcome == 'success'" in dispatch_block
    assert "steps.persist.outputs.persist_ok == 'true'" in dispatch_block
    assert 'main_sha="${{ steps.persist.outputs.main_sha }}"' in dispatch_block
    assert "STALE_MAIN_BEFORE_DISPATCH" in dispatch_block
    assert 'test "$remote_sha" = "$main_sha"' in dispatch_block
    assert 'gh workflow run "$DISPATCH_WORKFLOW" --ref main' in dispatch_block
    assert 'dispatch_started_at="$(date -u +%s)"' in dispatch_block
    assert "AUTO_DISPATCH_VERIFIED" in dispatch_block
    assert "AUTO_DISPATCH_UNVERIFIED" in dispatch_block
    assert 'timeout 12s gh run list --workflow "$DISPATCH_WORKFLOW"' in dispatch_block

    assert '--arg sha "$main_sha"' in dispatch_block
    assert '--arg sha "${{ github.sha }}"' not in dispatch_block

    assert "if: always() && steps.resolve.outcome == 'success'" in text

    test_control_plane_no_event_trigger_docs()
    test_control_plane_watchdog_contract()
    print("AUTONOMOUS_CONTROL_PLANE_DISPATCH_ORDER=PASS")
    return 0

def test_control_plane_no_event_trigger_docs() -> None:
    instructions = INSTRUCTIONS.read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")

    assert "### Event-triggered current-main reconciliation" not in instructions
    assert "### Event-driven failure triage" not in instructions
    assert "workflow_run payload is first-class evidence" not in instructions
    assert "workflow failure event" not in instructions
    assert "workflow_run failure event受信時" not in source
    assert "completed failure eventを直接受ける" not in source
    assert "workflow_run payloadをfirst-class evidence" not in source
    assert "毎時07分UTCのschedule、manual dispatch、mainの意味のあるpushに限定する。" in source
    assert "次の定期cycleでFailure Memoryを読み、観測済みfailureをRESEARCH_HEALTHへ変換する。" in source


def test_control_plane_watchdog_contract() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane_watchdog.yml"
    text = workflow.read_text(encoding="utf-8")
    assert 'cron: "*/10 * * * *"' in text
    assert '  push:\n    branches:\n      - main' in text
    assert "workflow_dispatch:" in text
    assert "actions: write" in text
    assert "CONTROL_STATE_MISSING_OR_INVALID" in text
    assert "CONTROL_STATE_SHA_STALE" in text
    assert "DURABLE_ONLY_AHEAD" in text
    assert "MEANINGFUL_CHANGE_OR_DIVERGED" in text
    assert "compare/$state_sha...$CURRENT_MAIN_SHA" in text
    assert "results/research/" in text
    assert "results/automation_state/" in text
    assert "CONTROL_STATE_OLDER_THAN_3H30M" in text
    assert "active_any" in text
    assert "active_current_in_progress" in text
    assert "outdated_in_progress_ids" in text
    assert "ACTIVE_CONTROL_RUN" in text
    assert "CANCEL_OUTDATED_IN_PROGRESS_CONTROL_RUN" in text
    assert "RECENT_CONTROL_RUN" in text
    assert "CURRENT_MAIN_CONTROL_RUN_AFTER_RECOVERY" in text
    assert "active_current_after" in text
    assert "STALE_QUEUED_CONTROL_RUN" in text
    assert "queued_stale" in text
    assert "CONTROL_RUN_QUEUE_TIMEOUT" in text
    assert "gh run cancel" in text
    assert 'gh run list --repo "$repo" --workflow "$workflow"' in text
    assert 'gh run list --repo "$repo" --workflow autonomous_control_plane.yml' in text
    assert 'if [ "$active_current_in_progress" -gt 0 ] && [ "$run_recovery_needed" = false ]; then' in text
    assert 'if [ "$active_in_progress" -ne 0 ]; then' not in text
    assert "STALE_MAIN_BEFORE_WATCHDOG_DISPATCH" in text
    assert 'gh workflow run autonomous_control_plane.yml --ref main --repo "$repo"' in text
    inspect_marker = "      - name: Inspect control-plane state and live runs"
    inspect_pos = text.index(inspect_marker)
    gh_run_list_pos = text.index('gh run list --repo "$repo" --workflow "$workflow"', inspect_pos)
    checkout_candidates = (
        "uses: actions/checkout@v6",
        "uses: actions/checkout@v7",
    )
    checkout_positions = [text.index(marker) for marker in checkout_candidates if marker in text]
    assert checkout_positions, "watchdog must checkout a repository before gh run list"
    assert min(checkout_positions) < inspect_pos < gh_run_list_pos, (
        "watchdog checkout must precede repository-context-dependent gh run list"
    )


if __name__ == "__main__":
    raise SystemExit(main())