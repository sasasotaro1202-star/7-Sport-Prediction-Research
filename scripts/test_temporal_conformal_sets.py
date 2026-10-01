from __future__ import annotations

import numpy as np
import pytest

from src.temporal_conformal_sets import (
    prediction_set_metrics,
    validate_maturity,
    walk_forward_prediction_sets,
)


def fixture(n=80):
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pt = [base + timedelta(hours=i) for i in range(n)]
    mature = [t + timedelta(hours=1) for t in pt]
    y = np.array([0, 1, 2] * ((n + 2) // 3))[:n]
    p = np.tile(
        np.array([[0.80, 0.15, 0.05], [0.10, 0.80, 0.10], [0.05, 0.10, 0.85]]),
        ((n + 2) // 3, 1),
    )[:n]
    return y, p, pt, mature


def test_maturity_contract_rejects_impossible_or_unsorted_time():
    y, p, pt, mature = fixture(10)
    bad = list(pt)
    bad[4] = bad[2]
    with pytest.raises(ValueError, match="monotonically"):
        validate_maturity(bad, mature)
    impossible = list(mature)
    impossible[3] = pt[3]
    impossible[3] = pt[3] - __import__("datetime").timedelta(minutes=1)
    with pytest.raises(ValueError, match="cannot precede"):
        validate_maturity(pt, impossible)


def test_same_prediction_time_is_excluded_and_maturity_is_required():
    y, p, pt, mature = fixture(70)
    pt[31] = pt[30]
    mature[29] = pt[60]
    out = walk_forward_prediction_sets(
        y, p, pt, mature,
        min_calibration=30,
        class_names=("home", "draw", "away"),
    )
    assert out["calibration_count"][31] == 29
    assert out["actions"][31] == "ABSTAIN"


def test_immature_outcomes_cannot_enter_earlier_cases():
    y, p, pt, mature = fixture(80)
    for i in range(20):
        mature[i] = pt[79]
    out = walk_forward_prediction_sets(
        y, p, pt, mature,
        min_calibration=10,
        class_names=("home", "draw", "away"),
    )
    assert out["calibration_count"][20] == 0
    assert out["maturity_gate"]["same_prediction_time_excluded"] is True


def test_rolling_window_is_bounded():
    y, p, pt, mature = fixture(80)
    out = walk_forward_prediction_sets(
        y, p, pt, mature,
        min_calibration=10,
        max_calibration=20,
        class_names=("home", "draw", "away"),
    )
    assert max(out["calibration_count"]) <= 20


def test_metrics_are_maturity_gated():
    y, p, pt, mature = fixture(80)
    out = walk_forward_prediction_sets(
        y, p, pt, mature,
        min_calibration=30,
        class_names=("home", "draw", "away"),
    )
    metrics = prediction_set_metrics(out, y)
    assert metrics["eligible_rows"] == 50.0
    assert 0.0 <= metrics["maturity_gated_fraction"] <= 1.0
    assert metrics["coverage_eligible"] >= 0.0
