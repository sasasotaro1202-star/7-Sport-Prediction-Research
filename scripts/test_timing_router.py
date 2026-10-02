#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from src.timing_route_registry import DEFAULT_LEAD, resolve_lead
import src.timing_route_builder as timing_builder


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    policy = json.loads((ROOT / "config/PREDICTION_TIMING_POLICY.json").read_text(encoding="utf-8"))
    assert DEFAULT_LEAD == 60
    assert timing_builder.DEFAULT_LEAD == 60
    assert callable(timing_builder.build)
    timing_src = (ROOT / "src/timing_route_builder.py").read_text(encoding="utf-8")
    assert "datetime(fp.generated_at_utc) <= datetime(fp.prediction_cutoff_at_utc)" in timing_src
    assert "feature_snapshot_hash" in timing_src
    assert policy["default_preferred_lead_minutes"] == 60
    assert 30 in policy["allowed_lead_minutes"]
    assert policy["selection"]["require_oos_timing_evidence_for_nondefault"] is True
    assert policy["selection"]["require_frozen_holdout_for_nondefault"] is True

    lead, status = resolve_lead("basketball", {"matched": True, "profile_id": "basketball:competition:missing-test"})
    assert lead == 60 and status == "DEFAULT_GUIDELINE"

    future = (ROOT / "src/future_predictor.py").read_text(encoding="utf-8")
    registry = (ROOT / "src/timing_route_registry.py").read_text(encoding="utf-8")
    assert "timing_route" in future
    assert "--adaptive-timing" in future
    assert "TIMING_ROUTE_ACCEPTED" in registry
    assert "selected_lead" in future and "selection_status" in future
    assert "PREDICTION_LEAD_MINUTES_DEFAULT=60" in future

    workflow = (ROOT / ".github/workflows/pre_event_prediction.yml").read_text(encoding="utf-8")
    assert "--lead-minutes" in workflow
    assert "--timing-shadow" in workflow
    assert "lead_minutes" in workflow
    assert "60" in workflow
    assert "pre-event-prediction-${{ github.event_name }}-${{ matrix.sport }}" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'schedule' }}" in workflow

    production = (ROOT / ".github/workflows/v4_5_15_production.yml").read_text(encoding="utf-8")
    assert "--lead-minutes 60 --min-lead-minutes 45 --max-lead-minutes 75 --target-scope-only" in production
    assert "--adaptive-timing --lead-minutes 30" not in production

    audit = (ROOT / "src/pre_event_prediction_audit.py").read_text(encoding="utf-8")
    assert "resolve_lead" in audit
    assert "TIMING_ROUTE_ACCEPTED" in audit

    print("ADAPTIVE_TIMING_ROUTER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
