from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "production_failure_recovery.yml"

ACTIVE = {"queued", "in_progress", "waiting", "requested", "pending"}


def _decision(current_sha: str, original_sha: str, current_run_id: int, runs: list[dict[str, object]]) -> str:
    active_current = [
        r for r in runs
        if int(r.get("id", -1)) != current_run_id
        and str(r.get("head_sha") or "") == current_sha
        and str(r.get("status") or "") in ACTIVE
    ]
    if active_current:
        return "COALESCE"
    if current_sha != original_sha:
        return "DISPATCH_FRESH_CURRENT_MAIN"
    return "RERUN_FAILED_ON_SAME_SHA"


def test_active_current_main_coalesces_stale_recovery() -> None:
    assert _decision(
        "current-main",
        "failed-old",
        100,
        [{"id": 200, "status": "in_progress", "head_sha": "current-main"}],
    ) == "COALESCE"


def test_active_current_main_coalesces_same_sha_retry() -> None:
    assert _decision(
        "current-main",
        "current-main",
        100,
        [{"id": 201, "status": "queued", "head_sha": "current-main"}],
    ) == "COALESCE"


def test_stale_failure_dispatches_fresh_current_main_when_no_active_run_exists() -> None:
    assert _decision("current-main", "failed-old", 100, []) == "DISPATCH_FRESH_CURRENT_MAIN"


def test_same_sha_failure_retries_failed_jobs_when_no_active_run_exists() -> None:
    assert _decision("current-main", "current-main", 100, []) == "RERUN_FAILED_ON_SAME_SHA"


def test_current_run_is_excluded_from_duplicate_detection() -> None:
    assert _decision(
        "current-main",
        "failed-old",
        100,
        [{"id": 100, "status": "in_progress", "head_sha": "current-main"}],
    ) == "DISPATCH_FRESH_CURRENT_MAIN"


def test_workflow_contains_fail_closed_duplicate_guard_before_dispatch() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_fragments = [
        "Coalesce duplicate recovery requests and retry once",
        "runs_json=",
        "active_current_main=",
        "RECOVERY_COALESCED_ACTIVE_CURRENT_MAIN",
        'if [ "$active_current_main" -gt 0 ]; then',
        "exit 0",
        'gh workflow run "${WORKFLOW_ID}" --ref main --repo "${REPOSITORY}"',
        'gh run rerun "${RUN_ID}" --failed --repo "${REPOSITORY}"',
    ]
    for fragment in required_fragments:
        assert fragment in text, f"missing recovery contract fragment: {fragment}"

    guard = text[text.index("      - name: Coalesce duplicate recovery requests and retry once"):]
    assert guard.index('if [ "$active_current_main" -gt 0 ]; then') < guard.index(
        'gh workflow run "${WORKFLOW_ID}" --ref main --repo "${REPOSITORY}"'
    )
    assert guard.index('if [ "$active_current_main" -gt 0 ]; then') < guard.index(
        'gh run rerun "${RUN_ID}" --failed --repo "${REPOSITORY}"'
    )


def main() -> None:
    test_active_current_main_coalesces_stale_recovery()
    test_active_current_main_coalesces_same_sha_retry()
    test_stale_failure_dispatches_fresh_current_main_when_no_active_run_exists()
    test_same_sha_failure_retries_failed_jobs_when_no_active_run_exists()
    test_current_run_is_excluded_from_duplicate_detection()
    test_workflow_contains_fail_closed_duplicate_guard_before_dispatch()
    print("PRODUCTION_FAILURE_RECOVERY_DEDUP=PASS")


if __name__ == "__main__":
    main()
