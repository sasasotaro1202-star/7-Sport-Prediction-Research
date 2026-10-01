#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from src.timing_route_registry import DEFAULT_LEAD, resolve_lead


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    policy = json.loads((ROOT / "config/PREDICTION_TIMING_POLICY.json").read_text(encoding="utf-8"))
    assert DEFAULT_LEAD == 30
    assert policy["default_preferred_lead_minutes"] == 30
    assert 30 in policy["allowed_lead_minutes"]
    assert policy["selection"]["require_oos_timing_evidence_for_nondefault"] is True
    assert policy["selection"]["require_frozen_holdout_for_nondefault"] is True

    lead, status = resolve_lead("basketball", {"matched": True, "profile_id": "basketball:competition:missing-test"})
    assert lead == 30 and status == "DEFAULT_GUIDELINE"

    future = (ROOT / "src/future_predictor.py").read_text(encoding="utf-8")
    registry = (ROOT / "src/timing_route_registry.py").read_text(encoding="utf-8")
    assert "timing_route" in future
    assert "--adaptive-timing" in future
    assert "TIMING_ROUTE_ACCEPTED" in registry
    assert "selected_lead" in future and "selection_status" in future

    workflow = (ROOT / ".github/workflows/pre_event_prediction.yml").read_text(encoding="utf-8")
    assert "--adaptive-timing" in workflow
    assert "--timing-shadow" in workflow
    assert "90" in workflow

    audit = (ROOT / "src/pre_event_prediction_audit.py").read_text(encoding="utf-8")
    assert "resolve_lead" in audit
    assert "TIMING_ROUTE_ACCEPTED" in audit

    print("ADAPTIVE_TIMING_ROUTER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
