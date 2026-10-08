"""Repository-wide guard against accidental GitHub Actions event storms.

This is a static safety contract. It does not infer runtime success and does not
change production/prediction behavior. Every workflow should have bounded
concurrency, and push triggers must be scoped by paths or branches.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def trigger_block(text: str) -> str:
    """Return the top-level on: YAML section without a YAML dependency.

    The repository workflows use the canonical multi-line GitHub Actions trigger
    shape. Any missing or malformed trigger header fails closed.
    """
    match = re.search(r'(?m)^(?:"on"|on):\s*$\n', text)
    if not match:
        raise AssertionError("workflow is missing a canonical on: block")

    remainder = text[match.end():]
    next_top_level = re.search(r"(?m)^[A-Za-z0-9_.-]+:\s*$", remainder)
    end = match.end() + (next_top_level.start() if next_top_level else len(remainder))
    return text[match.end():end]


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
                or re.search(r"(?m)^\s{4}paths-ignore:\s*$", block)
            ), f"{path.name}: push trigger is not scoped by paths/branches"

    control_plane = (WORKFLOWS / "autonomous_control_plane.yml").read_text(encoding="utf-8")
    control_block = trigger_block(control_plane)
    assert "workflow_run:" not in control_block
    assert "schedule:" in control_block
    assert "workflow_dispatch:" in control_block
    assert "push:" in control_block

    keepalive = (WORKFLOWS / "repository_activity_keepalive.yml").read_text(encoding="utf-8")
    keepalive_block = trigger_block(keepalive)
    assert "workflow_run:" not in keepalive_block
    assert 'cron: "17 3 1,15 * *"' in keepalive
    assert "git push origin HEAD:main" in keepalive
    assert "git push --force" not in keepalive
    assert "git push -f" not in keepalive

    lightweight = (WORKFLOWS / "lightweight_regression.yml").read_text(encoding="utf-8")
    lightweight_block = trigger_block(lightweight)
    assert "paths:" in lightweight_block, "lightweight regression push trigger must be path-scoped"
    assert "paths-ignore:" not in lightweight_block, "lightweight regression must not rely on a result-file ignore list"
    for required in ("src/**", "scripts/**", ".github/workflows/**", "config/**"):
        assert required in lightweight_block, f"lightweight regression missing source path {required}"

    print(f"WORKFLOW_EVENT_STORM_GUARD=PASS workflows={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
