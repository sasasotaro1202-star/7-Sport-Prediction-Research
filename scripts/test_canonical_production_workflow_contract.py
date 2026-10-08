#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v4_5_15_production.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")

    # Canonical production is schedule/manual only. Repository pushes are
    # handled by lightweight/invariant validation and must not start heavy
    # production collection/research.
    trigger_header = text.split("permissions:", 1)[0]
    assert "on:" in trigger_header
    assert "workflow_dispatch:" in trigger_header
    assert "schedule:" in trigger_header
    assert "  push:" not in trigger_header
    assert "workflow_run:" not in trigger_header
    assert "repository_dispatch:" not in trigger_header
    assert "17 * * * *" in trigger_header

    # The active production matrix must remain exactly the five canonical lanes.
    matrix_match = re.search(
        r"(?ms)^      matrix:\n        sport: \[(.*?)\]\n",
        text,
    )
    assert matrix_match, "production sport matrix missing"
    sports = [item.strip() for item in matrix_match.group(1).split(",") if item.strip()]
    assert sports == ["valorant", "basketball", "volleyball", "ufc", "rizin"], sports

    # Lock the exact indentation contract for the guarded main writer.
    push_block = (
        '            if PYTHONPATH=. python scripts/reliable_main_push.py \\\n'
        '              --expected-parent "$(git rev-parse HEAD^)" \\\n'
        '              --attempts 6 \\\n'
        '              --initial-delay 3 \\\n'
        '              --max-delay 30; then exit 0; fi'
    )
    assert push_block in text

    persist_start = text.index("      - name: Persist safe outputs")
    final_start = text.index("      - name: Final production failure verdict")
    persist = text[persist_start:final_start]
    assert "release_gate.json" in persist
    assert "publishable_artifacts" in persist
    assert "git diff --cached --check" in persist
    assert "reliable_main_push.py" in persist

    print("CANONICAL_PRODUCTION_TRIGGER_CONTRACT=PASS")
    print("ACTIVE_SPORTS=" + ",".join(sports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
