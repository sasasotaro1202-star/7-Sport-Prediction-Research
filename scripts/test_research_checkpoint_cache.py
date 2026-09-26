"""Static regression for persistent All-Sport Research checkpoints."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "all_sport_research.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/cache/restore@v4" in text
    assert "nine-sport-research-db-v4-${{ matrix.sport }}-" in text
    assert "name: Persist research database checkpoint" in text
    assert "actions/cache/save@v4" in text
    assert "path: data/db" in text
    assert "key: nine-sport-research-db-v4-${{ matrix.sport }}-${{ github.run_id }}" in text

    save_pos = text.index("name: Persist research database checkpoint")
    upload_pos = text.index("name: Upload sport research evidence")
    assert save_pos < upload_pos, "checkpoint must be persisted before evidence upload"

    print("RESEARCH_CHECKPOINT_CACHE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
