"""Static regression contract for stale-SHA PIT recovery in the production watchdog."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "production_watchdog.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")

    stale_start = text.index("      - name: Cancel stale unfinished heavy runs from old commits only when unsafe")
    stale_end = text.index("      - name: Ensure validated latest-main production is continuously scheduled", stale_start)
    stale = text[stale_start:stale_end]

    # gh returns a JSON array; stale-run recovery must explicitly emit one TSV
    # row per active run before shell read consumes it.
    assert '--jq' in stale
    assert '.status=="queued"' in stale
    assert '.status=="in_progress"' in stale
    assert '.status=="waiting"' in stale
    assert '.status=="requested"' in stale
    assert '.status=="pending"' in stale
    assert '| @tsv' in stale
    assert "while IFS=

    pit_start = text.index("      - name: Backfill a missed 9-hour PIT boundary once per boundary window")
    pit_end = text.index("      - name: Ensure pre-event T-60 prediction heartbeat", pit_start)
    pit = text[pit_start:pit_end]

    # Boundary attempts must be scoped to the current main SHA. Otherwise an
    # obsolete queued run from an older SHA can permanently suppress recovery.
    assert 'attempt_in_boundary=' in pit
    assert 'select(.headSha==$sha and (.event=="schedule" or .event=="workflow_dispatch")' in pit
    assert '--arg sha "$main_sha"' in pit
    assert 'Only an attempt pinned to the current main SHA counts against this' in pit

    print("PRODUCTION_WATCHDOG_PIT_RECOVERY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
\\t' read -r run_id status _event _created_at head_sha" in stale

    pit_start = text.index("      - name: Backfill a missed 9-hour PIT boundary once per boundary window")
    pit_end = text.index("      - name: Ensure pre-event T-60 prediction heartbeat", pit_start)
    pit = text[pit_start:pit_end]

    # Boundary attempts must be scoped to the current main SHA. Otherwise an
    # obsolete queued run from an older SHA can permanently suppress recovery.
    assert 'attempt_in_boundary=' in pit
    assert 'select(.headSha==$sha and (.event=="schedule" or .event=="workflow_dispatch")' in pit
    assert '--arg sha "$main_sha"' in pit
    assert 'Only an attempt pinned to the current main SHA counts against this' in pit

    print("PRODUCTION_WATCHDOG_PIT_RECOVERY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
