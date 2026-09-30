#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from src.scope_expansion_gate import candidate_priority

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

    assert 'entry["activation_allowed"] = False' in script
    assert "ADVANCE_ONE_CANDIDATE_ONLY" in script
    assert "PIT_EVIDENCE_INCOMPLETE" in script
    assert "explicit_scope_admission" in script
    assert "consecutive_clean_runs" in script

    from src.scope_expansion_gate import _stage_from_evidence

    low = {"events": 0, "verified_outcomes": 0, "pit_ratio": 0.0}
    assert _stage_from_evidence("x", None, low, policy)[0] == "METADATA_CHECKED"
    data_only = {"events": 120, "verified_outcomes": 80, "pit_ratio": 0.50}
    assert _stage_from_evidence("x", None, data_only, policy)[0] == "DATA_FEASIBLE"
    pit_ok = {"events": 120, "verified_outcomes": 80, "pit_ratio": 0.95}
    assert _stage_from_evidence("x", None, pit_ok, policy)[0] == "PIT_VALIDATED"
    shadow = {
        "shadow_status": "PASS",
        "oos_status": "PASS",
        "robustness_status": "PASS",
        "calibration_status": "PASS",
        "frozen_holdout_status": "PASS",
        "limited_production_status": "PASS",
        "recovery_status": "PASS",
        "important_case_status": "PASS",
        "stable_production_status": "PASS",
        "scale_up_status": "PASS",
        "explicit_scope_admission": True,
        "consecutive_clean_runs": 6,
    }
    assert _stage_from_evidence("x", shadow, pit_ok, policy)[0] == "SCALE_UP"

    low_priority = candidate_priority({"stage": "DATA_FEASIBLE", "metrics": {"events": 120, "verified_outcomes": 80, "pit_ratio": 0.50}}, policy)
    high_priority = candidate_priority({"stage": "PIT_VALIDATED", "metrics": {"events": 180, "verified_outcomes": 150, "pit_ratio": 0.99}}, policy)
    assert high_priority > low_priority

    no_admission = dict(shadow)
    no_admission["explicit_scope_admission"] = False
    assert _stage_from_evidence("x", no_admission, pit_ok, policy)[0] == "OOS_ROBUSTNESS"

    print("SCOPE_EXPANSION_POLICY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
