"""Static regression for persistent All-Sport Research checkpoints."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "all_sport_research.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    restore = text[text.index("name: Restore latest safe database cache"):text.index("name: Validate/repair restored database")]
    save = text[text.index("name: Persist research database checkpoint"):text.index("name: Upload sport research evidence")]

    assert "actions/cache/restore@v4" in restore
    assert "path: data/db" in restore
    research_key = "nine-sport-research-db-v4-${{ matrix.sport }}-"
    pit_key = "nine-sport-target-db-v4-${{ matrix.sport }}-pit-"
    target_key = "nine-sport-target-db-v4-${{ matrix.sport }}-"
    assert research_key in restore
    assert pit_key in restore
    assert target_key in restore
    assert restore.index(research_key) < restore.index(pit_key) < restore.index(target_key), (
        "persistent research checkpoint must outrank production cache fallbacks"
    )

    assert "name: Persist research database checkpoint" in save
    assert "if: success()" in save
    assert "actions/cache/save@v4" in save
    assert "path: data/db" in save
    run_key = "key: nine-sport-research-db-v4-${{ matrix.sport }}-${{ github.run_id }}"
    assert run_key in save
    assert "github.run_id" in save

    save_pos = text.index("name: Persist research database checkpoint")
    upload_pos = text.index("name: Upload sport research evidence")
    assert save_pos < upload_pos, "checkpoint must be persisted before evidence upload"

    print("RESEARCH_CHECKPOINT_CACHE=PASS")
    print("RESEARCH_CHECKPOINT_PRIORITY=PASS")
    print("RESEARCH_CHECKPOINT_SUCCESS_ONLY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())