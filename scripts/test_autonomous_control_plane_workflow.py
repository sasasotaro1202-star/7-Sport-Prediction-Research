from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/autonomous_control_plane.yml"


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
    assert "push:" in text
    assert text.count("  push:") == 1
    assert "'src/**'" in text
    assert "'scripts/**'" in text
    assert "'.github/workflows/**'" in text
    assert "'config/**'" in text
    assert "Active-Scope Target v4.5.15 Production" in text
    assert "PIT History Expansion" in text
    assert "Production Failure Recovery" in text
    assert "Autonomous Control Plane Regression" in text
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
    assert 'if [ "${{ github.event_name }}" = "schedule" ] || [ "${{ github.event_name }}" = "workflow_dispatch" ]; then' in reconcile_block
    assert 'elif [ "${{ github.event_name }}" = "push" ]; then' in reconcile_block

    persist_block = text[persist:dispatch]
    dispatch_block = text[dispatch:final]

    assert "cancel-in-progress: false" in text
    assert "id: persist" in persist_block
    assert 'git ls-files --error-unmatch -- "$state_path"' in persist_block
    assert 'CONTROL_PLANE_STATE_NOT_TRACKED path=$state_path' in persist_block
    assert 'echo "persist_ok=true" >> "$GITHUB_OUTPUT"' in persist_block
    assert 'echo "main_sha=' in persist_block
    assert 'remote_sha="$(gh api "repos/${{ github.repository }}/git/ref/heads/main"' in persist_block

    assert "steps.control.outcome == 'success'" in dispatch_block
    assert "steps.persist.outputs.persist_ok == 'true'" in dispatch_block
    assert 'main_sha="${{ steps.persist.outputs.main_sha }}"' in dispatch_block
    assert "STALE_MAIN_BEFORE_DISPATCH" in dispatch_block
    assert 'test "$remote_sha" = "$main_sha"' in dispatch_block
    assert 'gh workflow run "$DISPATCH_WORKFLOW" --ref main' in dispatch_block

    assert '--arg sha "$main_sha"' in dispatch_block
    assert '--arg sha "${{ github.sha }}"' not in dispatch_block

    assert "if: always() && steps.resolve.outcome == 'success'" in text

    test_control_plane_watchdog_contract()
    print("AUTONOMOUS_CONTROL_PLANE_DISPATCH_ORDER=PASS")
    return 0

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
    assert 'if [ "$active_current_in_progress" -gt 0 ] && [ "$run_recovery_needed" = false ]; then' in text
    assert 'if [ "$active_in_progress" -ne 0 ]; then' not in text
    assert "STALE_MAIN_BEFORE_WATCHDOG_DISPATCH" in text
    assert 'gh workflow run autonomous_control_plane.yml --ref main --repo "$repo"' in text


if __name__ == "__main__":
    raise SystemExit(main())