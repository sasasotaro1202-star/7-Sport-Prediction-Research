"""Regression contract for safe main advancement during long-running research.

A long-running production/research run must keep fail-closed behavior when source,
code, or configuration changes land on main, but it must not be invalidated merely
because the autonomous control plane persists its durable state.
"""

from pathlib import Path

REQUIRED_WORKFLOWS = (
    Path(".github/workflows/v4_5_15_production.yml"),
    Path(".github/workflows/24h_autonomous_research.yml"),
    Path(".github/workflows/24h_autonomous_research_watchdog.yml"),
)

SAFE_MARKERS = (
    "main-advance compatibility",
    "results/research/autonomous_control_plane.json",
    "results/research/automation_health.json",
    "results/research/research_queue.jsonl",
    "results/research/autonomous_action_log.jsonl",
    "results/automation_state/",
    "results/failure_memory.jsonl",
    "merge-base --is-ancestor",
    "git diff --name-only",
)

FORBIDDEN_EXACT_GUARD = 'test "${remote_sha}" = "${GITHUB_SHA}" || {'

def main() -> None:
    missing = [str(p) for p in REQUIRED_WORKFLOWS if not p.is_file()]
    assert not missing, f"missing workflow(s): {missing}"
    combined = "\n".join(p.read_text(encoding="utf-8") for p in REQUIRED_WORKFLOWS)
    for marker in SAFE_MARKERS:
        assert marker in combined, f"missing safe-advance marker: {marker}"
    assert FORBIDDEN_EXACT_GUARD not in combined, "old unconditional latest-main SHA guard remains"

if __name__ == "__main__":
    main()
