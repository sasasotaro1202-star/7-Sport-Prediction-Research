from __future__ import annotations

import numpy as np
import pytest
from datetime import datetime, timedelta, timezone

from src.temporal_conformal_prediction_sets import (
    prediction_set_metrics,
    temporal_binary_prediction_sets,
    validate_maturity_contract,
)


def _fixture(n=70):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pt_dt = [base + timedelta(hours=h) for h in range(n)]
    pt = [dt.isoformat() for dt in pt_dt]
    mature = [(dt + timedelta(minutes=30)).isoformat() for dt in pt_dt]
    y = np.asarray([0, 1] * ((n + 1) // 2))[:n]
    p = np.asarray([0.80, 0.20] * ((n + 1) // 2))[:n]
    return y, p, pt, mature


def test_maturity_contract_fail_closed():
    y, p, pt, mature = _fixture(8)
    bad_pt = pt.copy()
    bad_pt[3] = "2025-12-31T23:00:00+00:00"
    with pytest.raises(ValueError, match="monotonically"):
        validate_maturity_contract(bad_pt, mature)

    bad_mature = mature.copy()
    bad_mature[3] = "2026-01-01T02:00:00+00:00"
    with pytest.raises(ValueError, match="precedes"):
        validate_maturity_contract(pt, bad_mature)


def test_same_timestamp_and_immature_rows_are_excluded():
    y, p, pt, mature = _fixture(60)
    pt[10] = pt[9]
    mature[10] = "2026-01-03T00:00:00+00:00"
    # Keep row 11's own outcome confirmation valid; row 10 is the immature same-time row.
    mature[11] = "2026-01-01T11:30:00+00:00"

    out = temporal_binary_prediction_sets(
        y, p, pt, mature, min_calibration=10, max_calibration=20
    )
    assert out["calibration_count"][11] == 10
    assert out["maturity_contract"]["same_prediction_time_excluded"] is True


def test_bounded_temporal_calibration_window():
    y, p, pt, mature = _fixture(70)
    out = temporal_binary_prediction_sets(
        y, p, pt, mature, min_calibration=10, max_calibration=20
    )
    assert out["calibration_count"].max() <= 20
    assert out["calibration_count"][30] == 20


def test_eligible_metrics_ignore_warmup_abstentions():
    y, p, pt, mature = _fixture(50)
    out = temporal_binary_prediction_sets(
        y, p, pt, mature, min_calibration=15
    )
    metrics = prediction_set_metrics(out, y)
    assert metrics["total_rows"] == 50
    assert metrics["eligible_rows"] == 35
    assert 0.0 <= metrics["eligible_fraction"] <= 1.0


def test_sets_become_non_empty_after_warmup():
    y, p, pt, mature = _fixture(45)
    out = temporal_binary_prediction_sets(
        y, p, pt, mature, alpha=0.10, min_calibration=10
    )
    assert out["actions"][0] == "ABSTAIN"
    assert out["eligible_rows"] == 35
    assert all(size >= 1 for size in out["set_size"][10:])

