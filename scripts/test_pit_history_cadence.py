from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    pit = (ROOT / ".github/workflows/pit_history_expansion.yml").read_text(encoding="utf-8")
    watchdog = (ROOT / ".github/workflows/production_watchdog.yml").read_text(encoding="utf-8")

    assert re.search(r"cron:\s*'47 0,9,18 \* \* \*'", pit), pit
    assert "47 */3 * * *" not in pit
    assert "  push:" not in pit
    assert "Determine PIT expansion execution mode" in pit
    assert "minute_delta=$((delta / 60))" not in pit
    assert "PIT_9H_MODE=SCHEDULED_00_47_09_47_18_47_UTC" in pit
    assert "Backfill a missed 9-hour PIT boundary once per boundary window" in watchdog
    assert "attempt_in_boundary" in watchdog
    assert '[ "$attempt_in_boundary" -eq 0 ]' in watchdog
    assert "boundary_index" in watchdog and "boundary_epoch" in watchdog

    print("PIT_HISTORY_9H_CADENCE=PASS")


if __name__ == "__main__":
    main()
