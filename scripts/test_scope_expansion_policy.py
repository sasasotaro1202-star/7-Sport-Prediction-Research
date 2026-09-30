#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
policy = json.loads((ROOT / "config/SCOPE_EXPANSION_POLICY.json").read_text(encoding="utf-8"))
project = json.loads((ROOT / "config/PROJECT_SCOPE_POLICY.json").read_text(encoding="utf-8"))
script = (ROOT / "src/scope_expansion_gate.py").read_text(encoding="utf-8")


def main() -> int:
    expected = [
        "DISCOVERED",
        "METADATA_CHECKED",
        "DATA_FEASIBLE",
        "PIT_VALIDATED",
        "SHADOW",
        "OOS_ROBUSTNESS",
        "LIMITED_PRODUCTION",
        "STABLE_PRODUCTION",
        "SCALE_UP",
    ]
    assert policy["stage_order"] == expected
    assert policy["no_implicit_activation"] is True
    assert policy["limits"]["max_new_targets_in_advanced_validation_per_cycle"] == 1
    assert policy["limits"]["max_new_production_admissions_per_cycle"] == 0

    active = set(project["active_prediction_scope"])
    deferred = {x["sport"] for x in policy["candidate_sources"]["deferred_sports"]}
    assert not active.intersection(deferred)

    assert '"activation_allowed": False' in script
    assert "ADVANCE_ONE_CANDIDATE_ONLY" in script
    assert "PIT_EVIDENCE_INCOMPLETE" in script
    assert "explicit_scope_admission" in script
    assert "consecutive_clean_runs" in script
    print("SCOPE_EXPANSION_POLICY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
