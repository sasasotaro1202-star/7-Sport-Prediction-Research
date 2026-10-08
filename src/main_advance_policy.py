"""Fail-closed policy for long-running runs while main advances.

Autonomous control-plane state and failure-memory commits may advance the main branch
without changing executable/configuration semantics. Long-running workflows may safely
continue across those durable-only commits, but any other main advancement invalidates
the run and must fail closed.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


SAFE_DURABLE_PATH_PREFIXES = (
    "results/research/autonomous_control_plane.json",
    "results/research/automation_health.json",
    "results/research/research_queue.jsonl",
    "results/research/autonomous_action_log.jsonl",
    "results/automation_state/",
    "results/failure_memory.jsonl",
)


@dataclass(frozen=True)
class MainAdvanceDecision:
    status: str
    base_sha: str
    current_sha: str
    changed_paths: tuple[str, ...]
    safe_paths: tuple[str, ...]
    unsafe_paths: tuple[str, ...]
    reason: str


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _is_safe_durable_path(path: str) -> bool:
    return any(
        path == prefix or (prefix.endswith("/") and path.startswith(prefix))
        for prefix in SAFE_DURABLE_PATH_PREFIXES
    )


def _repair_shallow_ancestry(
    base_sha: str,
    current_sha: str,
    *,
    cwd: Path | str = ".",
) -> bool:
    """Recover enough shallow history to verify a real ancestry relation."""
    root = Path(cwd)
    shallow = _run_git(
        ["rev-parse", "--is-shallow-repository"],
        root,
    )
    if shallow.returncode != 0 or shallow.stdout.strip().lower() != "true":
        return False

    for deepen in (64, 256, 1024):
        fetched = _run_git(
            ["fetch", f"--deepen={deepen}", "origin", "main"],
            root,
        )
        if fetched.returncode != 0:
            return False
        if _run_git(
            ["merge-base", "--is-ancestor", base_sha, current_sha],
            root,
        ).returncode == 0:
            return True

    return False


def classify_main_advance(
    base_sha: str,
    current_sha: str,
    *,
    cwd: Path | str = ".",
) -> MainAdvanceDecision:
    base_sha = base_sha.strip()
    current_sha = current_sha.strip()
    root = Path(cwd)

    if not base_sha or not current_sha:
        return MainAdvanceDecision(
            "UNVERIFIABLE",
            base_sha,
            current_sha,
            (),
            (),
            (),
            "missing_base_or_current_sha",
        )

    if base_sha == current_sha:
        return MainAdvanceDecision(
            "EXACT_CURRENT_MAIN",
            base_sha,
            current_sha,
            (),
            (),
            (),
            "run_sha_matches_current_main",
        )

    ancestor = _run_git(
        ["merge-base", "--is-ancestor", base_sha, current_sha],
        root,
    )
    if ancestor.returncode != 0:
        # GitHub Actions commonly checks out with fetch-depth=1. In that
        # environment the base commit may be outside the shallow boundary.
        # Repair only this evidence gap; true divergence remains fail-closed.
        if _repair_shallow_ancestry(
            base_sha,
            current_sha,
            cwd=root,
        ):
            ancestor = _run_git(
                ["merge-base", "--is-ancestor", base_sha, current_sha],
                root,
            )

    if ancestor.returncode != 0:
        return MainAdvanceDecision(
            "NON_DURABLE_CHANGE",
            base_sha,
            current_sha,
            (),
            (),
            (),
            "current_main_is_not_a_verified_descendant_of_run_sha",
        )

    diff = _run_git(
        ["diff", "--name-only", f"{base_sha}..{current_sha}"],
        root,
    )
    if diff.returncode != 0:
        return MainAdvanceDecision(
            "UNVERIFIABLE",
            base_sha,
            current_sha,
            (),
            (),
            (),
            f"git_diff_failed:{diff.returncode}",
        )

    changed = tuple(path for path in diff.stdout.splitlines() if path)
    if not changed:
        return MainAdvanceDecision(
            "UNVERIFIABLE",
            base_sha,
            current_sha,
            (),
            (),
            (),
            "main_sha_changed_without_observable_file_delta",
        )

    safe = tuple(path for path in changed if _is_safe_durable_path(path))
    unsafe = tuple(path for path in changed if not _is_safe_durable_path(path))
    if unsafe:
        return MainAdvanceDecision(
            "NON_DURABLE_CHANGE",
            base_sha,
            current_sha,
            changed,
            safe,
            unsafe,
            "non_durable_main_change",
        )

    return MainAdvanceDecision(
        "DURABLE_ONLY",
        base_sha,
        current_sha,
        changed,
        safe,
        (),
        "only_control_plane_or_append_only_durable_state_changed",
    )


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--current-sha", required=True)
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args()

    decision = classify_main_advance(
        args.base_sha,
        args.current_sha,
        cwd=args.cwd,
    )

    print(
        f"MAIN_ADVANCE_STATUS={decision.status} "
        f"base={decision.base_sha} current={decision.current_sha} "
        f"reason={decision.reason}"
    )
    if decision.changed_paths:
        print("MAIN_ADVANCE_CHANGED=" + ",".join(decision.changed_paths))
    if decision.unsafe_paths:
        print("MAIN_ADVANCE_UNSAFE=" + ",".join(decision.unsafe_paths))

    return 0 if decision.status in {"EXACT_CURRENT_MAIN", "DURABLE_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(_main())
