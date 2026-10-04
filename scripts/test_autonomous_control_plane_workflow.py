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

    assert "workflow_run:" in text
    assert "Active-Scope Target v4.5.15 Production" in text
    assert "PIT History Expansion" in text
    assert "Production Failure Recovery" in text
    assert "Autonomous Control Plane Regression" in text
    assert "github.event.workflow_run.conclusion == 'failure'" in text
    assert "CONTROL_PLANE_EVENT_WORKFLOW" in text
    assert "CONTROL_PLANE_EVENT_CONCLUSION" in text
    assert "CONTROL_PLANE_EVENT_HEAD_SHA" in text
    assert "CONTROL_PLANE_EVENT_ANCESTOR_OF_MAIN" in text

    reconcile_marker = "      - name: Resolve current main for control-plane execution"
    assert reconcile_marker in text
    reconcile = text.index(reconcile_marker)
    regression_marker = "      - name: Run control-plane regression"
    regression = text.index(regression_marker)
    assert reconcile < regression, "current-main resolution must precede control-plane execution"
    reconcile_block = text[reconcile:regression]
    assert "github.event_name == 'workflow_run'" in reconcile_block
    assert "git fetch origin main --depth=1" in reconcile_block
    assert 'git checkout --detach "$remote_sha"' in reconcile_block
    assert "compare/$event_head...$remote_sha" in reconcile_block
    assert 'echo "CONTROL_PLANE_EVENT_ANCESTOR_OF_MAIN=$ancestor"' in reconcile_block

    persist_block = text[persist:dispatch]
    dispatch_block = text[dispatch:final]

    assert "id: persist" in persist_block
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

    print("AUTONOMOUS_CONTROL_PLANE_DISPATCH_ORDER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())