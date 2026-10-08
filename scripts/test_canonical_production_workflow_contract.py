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

    # Lock the shell contracts that previously caused the verified Actionlint
    # failure. The production cache-gate here-doc must close inside its scalar,
    # and pre-event GITHUB_OUTPUT writes must be grouped rather than redirected
    # repeatedly.
    cache_gate_start = text.index("      - name: Gate active-scope database cache publication")
    cache_save_start = text.index("      - name: Save database", cache_gate_start)
    cache_gate = text[cache_gate_start:cache_save_start]
    assert "          python - <<'PY'\n" in cache_gate
    assert cache_gate.rstrip().endswith("          PY")
    assert "PY\n\n      - name: Save database" in text

    pre_event = (ROOT / ".github" / "workflows" / "pre_event_prediction.yml").read_text(encoding="utf-8")
    predict_start = pre_event.index("      - name: Generate requested prediction lane")
    adaptive_start = pre_event.index("      - name: Generate adaptive timing research lane", predict_start)
    predict_block = pre_event[predict_start:adaptive_start]
    assert '{\n            echo "lead=$requested_lead"' in predict_block
    assert '} >> "$GITHUB_OUTPUT"' in predict_block
    assert 'echo "lead=$requested_lead" >> "$GITHUB_OUTPUT"' not in predict_block

    watchdog = (ROOT / ".github" / "workflows" / "production_watchdog.yml").read_text(encoding="utf-8")
    stale_start = watchdog.index("      - name: Cancel stale unfinished heavy runs from old commits only when unsafe")
    ensure_start = watchdog.index("      - name: Ensure validated latest-main production is continuously scheduled", stale_start)
    stale_block = watchdog[stale_start:ensure_start]
    assert "while read -r run_id status _event _created_at head_sha; do" in stale_block
    assert "while IFS=
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
\\t' read -r run_id status event created_at head_sha; do" not in stale_block

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
