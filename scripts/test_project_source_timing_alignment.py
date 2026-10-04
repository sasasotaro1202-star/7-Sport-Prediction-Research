#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    policy = json.loads(
        (ROOT / "config/PREDICTION_TIMING_POLICY.json").read_text(encoding="utf-8")
    )
    source = (ROOT / "docs/PROJECT_SOURCE.md").read_text(encoding="utf-8")

    selection = policy["selection"]
    scheduler = policy["scheduler"]

    assert policy["default_preferred_lead_minutes"] == 60
    assert selection["production_default"] == 60
    assert scheduler["guideline_target_minutes"] == 60
    assert scheduler["target_lead_minutes"] == 60
    assert scheduler["selection_mode"] == "scheduled-60m-default;manual-lead-configurable"

    assert "T-60分を主要実装基準とする" in source
    assert "30分前予測を主要実装基準とする" not in source

    print("PROJECT_SOURCE_TIMING_ALIGNMENT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
