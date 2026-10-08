"""Regression tests for long-running runs surviving durable-only main commits."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from src.main_advance_policy import _repair_shallow_ancestry, _run_git, classify_main_advance


POLICY = Path("src/main_advance_policy.py")

WORKFLOWS = (
    Path(".github/workflows/v4_5_15_production.yml"),
    Path(".github/workflows/24h_autonomous_research.yml"),
    Path(".github/workflows/24h_autonomous_research_watchdog.yml"),
    Path(".github/workflows/pit_history_expansion.yml"),
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _commit(cwd: Path, message: str) -> str:
    _git(cwd, "add", ".")
    _git(cwd, "commit", "-m", message)
    return _git(cwd, "rev-parse", "HEAD")


def test_durable_only_main_advance_is_allowed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "test@example.invalid")
        _git(repo, "config", "user.name", "test")
        (repo / "src").mkdir()
        (repo / "src" / "model.py").write_text("VERSION = 1\\n", encoding="utf-8")
        base = _commit(repo, "base")

        durable = repo / "results" / "research"
        durable.mkdir(parents=True)
        (durable / "autonomous_control_plane.json").write_text("{}\\n", encoding="utf-8")
        current = _commit(repo, "control state")

        decision = classify_main_advance(base, current, cwd=repo)
        assert decision.status == "DURABLE_ONLY"
        assert decision.unsafe_paths == ()


def test_shallow_history_repair_recovers_real_ancestor() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "source"
        remote = root / "remote.git"
        clone = root / "clone"
        source.mkdir()
        _git(source, "init", "-q")
        _git(source, "config", "user.email", "test@example.invalid")
        _git(source, "config", "user.name", "test")
        _git(source, "checkout", "-q", "-b", "main")
        (source / "README.md").write_text("base\\n", encoding="utf-8")
        _commit(source, "base")
        base = _git(source, "rev-parse", "HEAD")
        for index in range(3):
            (source / "README.md").write_text(f"step {index}\\n", encoding="utf-8")
            _commit(source, f"step {index}")
        current = _git(source, "rev-parse", "HEAD")

        _git(source, "clone", "--bare", str(source), str(remote))
        _git(source, "clone", "--depth", "1", f"file://{remote}", str(clone))

        shallow = _run_git(["rev-parse", "--is-shallow-repository"], clone)
        assert shallow.returncode == 0
        assert shallow.stdout.strip().lower() == "true"
        assert _run_git(["merge-base", "--is-ancestor", base, current], clone).returncode != 0

        assert _repair_shallow_ancestry(base, current, cwd=clone) is True
        assert _run_git(["merge-base", "--is-ancestor", base, current], clone).returncode == 0

def test_diverged_main_is_rejected_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "test@example.invalid")
        _git(repo, "config", "user.name", "test")
        (repo / "README.md").write_text("root\\n", encoding="utf-8")
        _commit(repo, "base")
        branch = _git(repo, "branch", "--show-current")

        _git(repo, "checkout", "-q", "-b", "other")
        (repo / "other.txt").write_text("other\\n", encoding="utf-8")
        other = _commit(repo, "other")
        _git(repo, "checkout", "-q", branch)
        (repo / "main.txt").write_text("main\\n", encoding="utf-8")
        current = _commit(repo, "main")

        decision = classify_main_advance(other, current, cwd=repo)
        assert decision.status == "NON_DURABLE_CHANGE"


def test_workflows_use_compatibility_policy_not_unconditional_sha_guard() -> None:
    workflow_text = "\\n".join(path.read_text(encoding="utf-8") for path in WORKFLOWS)
    policy_text = POLICY.read_text(encoding="utf-8")
    assert "src.main_advance_policy" in workflow_text
    assert 'STALE_PIT_WORKFLOW_SHA' in workflow_text
    assert 'if: ! PYTHONPATH=. python -m src.main_advance_policy' not in workflow_text
    assert 'PYTHONPATH=. python -m src.main_advance_policy --base-sha "$GITHUB_SHA" --current-sha "$main_sha"' in workflow_text
    watchdog_text = Path(".github/workflows/24h_autonomous_research_watchdog.yml").read_text(encoding="utf-8")
    assert "git fetch origin main" in watchdog_text
    assert watchdog_text.index("git fetch origin main") < watchdog_text.index("from src.main_advance_policy import classify_main_advance")
    assert '"merge-base", "--is-ancestor"' in policy_text
    assert '"rev-parse", "--is-shallow-repository"' in policy_text
    assert '"fetch", f"--deepen={deepen}", "origin", "main"' in policy_text
    assert '"diff", "--name-only"' in policy_text
    assert "results/research/autonomous_control_plane.json" in policy_text
    assert 'test "${remote_sha}" = "${GITHUB_SHA}" || {' not in workflow_text


if __name__ == "__main__":
    test_durable_only_main_advance_is_allowed()
    test_non_durable_main_advance_is_rejected()
    test_shallow_history_repair_recovers_real_ancestor()
    test_diverged_main_is_rejected_fail_closed()
    test_workflows_use_compatibility_policy_not_unconditional_sha_guard()
    print("main-advance compatibility tests: PASS")
