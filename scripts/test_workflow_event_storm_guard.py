"""Repository-wide guard against accidental GitHub Actions event storms.

This is a static safety contract. It does not infer runtime success and does not
change production/prediction behavior. Every workflow should have bounded
concurrency, and push triggers must be scoped by paths or branches.
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def trigger_block(text: str) -> str:
    match = re.search(r'(?m)^(?:"on"|on):\s*
    if not match:
        raise AssertionError("workflow is missing a canonical on: block")
    jobs = re.search(r"(?m)^jobs:\s*$", text[match.end() :])
    end = match.end() + (jobs.start() if jobs else len(text) - match.end())
    return text[match.end() : end]


def main() -> int:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, "no workflow files found"

    for path in files:
        text = path.read_text(encoding="utf-8")
        block = trigger_block(text)

        assert "concurrency:" in text, f"{path.name}: missing bounded concurrency"
        assert "runs-on:" in text, f"{path.name}: missing runner declaration"

        if re.search(r"(?m)^\s{2}push:\s*$", block):
            assert (
                re.search(r"(?m)^\s{4}(paths|branches):\s*$", block)
                or re.search(r"(?m)^\s{4}(paths-ignore):\s*$", block)
            ), f"{path.name}: push trigger is not scoped by paths/branches"

    control_plane = (WORKFLOWS / "autonomous_control_plane.yml").read_text(
        encoding="utf-8"
    )
    control_block = trigger_block(control_plane)
    assert "workflow_run:" not in control_block
    assert "schedule:" in control_block
    assert "workflow_dispatch:" in control_block
    assert "push:" in control_block

    keepalive = (WORKFLOWS / "repository_activity_keepalive.yml").read_text(
        encoding="utf-8"
    )
    keepalive_block = trigger_block(keepalive)
    assert "workflow_run:" not in keepalive_block
    assert 'cron: "17 3 1,15 * *"' in keepalive
    assert "git push origin HEAD:main" in keepalive
    assert "git push --force" not in keepalive
    assert "git push -f" not in keepalive

    print(f"WORKFLOW_EVENT_STORM_GUARD=PASS workflows={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
, text)
    if not match:
        raise AssertionError("workflow is missing a canonical on: block")
    jobs = re.search(r"(?m)^jobs:\s*$", text[match.end() :])
    end = match.end() + (jobs.start() if jobs else len(text) - match.end())
    return text[match.end() : end]


def main() -> int:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, "no workflow files found"

    for path in files:
        text = path.read_text(encoding="utf-8")
        block = trigger_block(text)

        assert "concurrency:" in text, f"{path.name}: missing bounded concurrency"
        assert "runs-on:" in text, f"{path.name}: missing runner declaration"

        if re.search(r"(?m)^\s{2}push:\s*$", block):
            assert (
                re.search(r"(?m)^\s{4}(paths|branches):\s*$", block)
                or re.search(r"(?m)^\s{4}(paths-ignore):\s*$", block)
            ), f"{path.name}: push trigger is not scoped by paths/branches"

    control_plane = (WORKFLOWS / "autonomous_control_plane.yml").read_text(
        encoding="utf-8"
    )
    control_block = trigger_block(control_plane)
    assert "workflow_run:" not in control_block
    assert "schedule:" in control_block
    assert "workflow_dispatch:" in control_block
    assert "push:" in control_block

    keepalive = (WORKFLOWS / "repository_activity_keepalive.yml").read_text(
        encoding="utf-8"
    )
    keepalive_block = trigger_block(keepalive)
    assert "workflow_run:" not in keepalive_block
    assert 'cron: "17 3 1,15 * *"' in keepalive
    assert "git push origin HEAD:main" in keepalive
    assert "git push --force" not in keepalive
    assert "git push -f" not in keepalive

    print(f"WORKFLOW_EVENT_STORM_GUARD=PASS workflows={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
