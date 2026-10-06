from __future__ import annotations

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

    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("Coalesce duplicate recovery requests and retry once")
    guard = text[start:]
    guard_idx = guard.index("RECOVERY_COALESCED_ACTIVE_CURRENT_MAIN")
    assert "active_current_main=" in guard
    assert "exit 0" in guard
    assert guard_idx < guard.index("gh workflow run ")
    assert guard_idx < guard.index("gh run rerun ")


def main() -> None:
    test_contract()
    print("PRODUCTION_FAILURE_RECOVERY_DEDUP=PASS")


if __name__ == "__main__":
    main()
