from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "production_failure_recovery.yml"
ACTIVE = {"queued", "in_progress", "waiting", "requested", "pending"}


def recovery_decision(current_sha: str, original_sha: str, current_run_id: int, runs: list[dict[str, object]]) -> str:
    active_current_main = [
        r for r in runs
        if int(r.get("id", -1)) != current_run_id
        and str(r.get("head_sha") or "") == current_sha
        and str(r.get("status") or "") in ACTIVE
    ]
    if active_current_main:
        return "COALESCE"
    return "DISPATCH_FRESH_CURRENT_MAIN" if current_sha != original_sha else "RERUN_FAILED_ON_SAME_SHA"


def test_contract() -> None:
    assert recovery_decision("m", "old", 100, [{"id": 200, "status": "in_progress", "head_sha": "m"}]) == "COALESCE"
    assert recovery_decision("m", "m", 100, [{"id": 201, "status": "queued", "head_sha": "m"}]) == "COALESCE"
    assert recovery_decision("m", "old", 100, []) == "DISPATCH_FRESH_CURRENT_MAIN"
    assert recovery_decision("m", "m", 100, []) == "RERUN_FAILED_ON_SAME_SHA"
    assert recovery_decision("m", "old", 100, [{"id": 100, "status": "in_progress", "head_sha": "m"}]) == "DISPATCH_FRESH_CURRENT_MAIN"

    def classify_failure(failed_jobs: list[str], conclusion: str, source_log: str) -> tuple[str, str | None]:
        names = " ".join(failed_jobs).lower()
        stale_guard_markers = (
            "STALE_PRODUCTION_WORKFLOW_SHA",
            "STALE_MERGE_RUN_SHA",
            "STALE_MERGE_WORKFLOW_SHA",
            "STALE_PUBLISH_RUN",
            "STALE_MAIN_BEFORE_PUSH",
        )
        if any(marker in source_log for marker in stale_guard_markers):
            return "AUTOMATION_FAILURE", "STALE_RUN_RECONCILIATION"
        if "pit" in names:
            return "PIT_WORKFLOW_FAILURE", None
        if "collect" in names or "backfill" in names:
            return "COLLECTION_WORKFLOW_FAILURE", None
        if "research" in names or "release gate" in names:
            return "RESEARCH_RELEASE_WORKFLOW_FAILURE", None
        if conclusion == "timed_out":
            return "WORKFLOW_TIMEOUT", None
        if conclusion == "startup_failure":
            return "WORKFLOW_STARTUP_FAILURE", None
        return "WORKFLOW_FAILURE", None

    assert classify_failure(
        ["Merge, research, and release gate"],
        "failure",
        "STALE_MERGE_RUN_SHA base=old current_main=new",
    ) == ("AUTOMATION_FAILURE", "STALE_RUN_RECONCILIATION")
    assert classify_failure(
        ["Merge, research, and release gate"],
        "failure",
        "ordinary research failure",
    ) == ("RESEARCH_RELEASE_WORKFLOW_FAILURE", None)
    assert classify_failure(
        ["Expand PIT history (basketball)"],
        "failure",
        "ordinary PIT failure",
    ) == ("PIT_WORKFLOW_FAILURE", None)

    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'git add results/failure_memory.jsonl' in text
    assert 'scripts/reliable_main_push.py' in text
    assert '--expected-parent "$(git rev-parse HEAD^)"' in text
    assert 'GH_TOKEN: ${{ github.token }}' in text
    assert 'git push origin HEAD:main' not in text
    push_helper = (ROOT / "scripts" / "reliable_main_push.py").read_text(encoding="utf-8")
    tree = ast.parse(push_helper)
    has_guarded_push = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.args, list) or not node.args:
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "run_capture":
            continue
        arg_values = []
        for arg in node.args:
            if not isinstance(arg, (ast.List, ast.Tuple)):
                break
            values = []
            for elt in arg.elts:
                if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
                    values = []
                    break
                values.append(elt.value)
            arg_values.append(values)
        if arg_values and arg_values[0] == ["git", "push", "origin", "HEAD:main"]:
            has_guarded_push = True
            break
    assert has_guarded_push, "reliable push helper must invoke guarded git push"
    assert 'verify_local_parent' in push_helper
    assert 'RELIABLE_PUSH_STALE_MAIN' in push_helper
    assert 'verify_remote_head' in push_helper
    assert 'classify_push_failure' in push_helper
    start = text.index("Recover once without replaying a stale SHA")
    guard = text[start:]
    guard_idx = guard.index("RECOVERY_COALESCED_ACTIVE_CURRENT_MAIN")
    assert "active_current_main=" in guard
    assert "exit 0" in guard
    assert guard_idx < guard.index("gh workflow run ")
    assert guard_idx < guard.index("gh run rerun ")

    memory_start = text.index("- name: Record append-only failure memory")
    memory_block = text[memory_start:]
    assert "STALE_RUN_RECONCILIATION" in memory_block
    assert "failure_signal" in memory_block
    assert "STALE_PUBLISH_RUN" in memory_block
    assert "classification_basis" in memory_block


def main() -> None:
    test_contract()
    print("PRODUCTION_FAILURE_RECOVERY_DEDUP=PASS")


if __name__ == "__main__":
    main()
