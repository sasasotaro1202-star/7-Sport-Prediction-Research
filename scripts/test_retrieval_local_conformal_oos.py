from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.retrieval_local_conformal_oos import (
    retrieval_local_metrics,
    retrieval_local_prediction_sets,
)


def fixture(n=80):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pt = [base + timedelta(hours=i) for i in range(n)]
    mature = [t + timedelta(hours=1) for t in pt]
    y = np.array([0, 1, 2] * ((n + 2) // 3))[:n]
    p = np.tile(
        np.array([[0.80, 0.15, 0.05], [0.10, 0.80, 0.10], [0.05, 0.10, 0.85]]),
        ((n + 2) // 3, 1),
    )[:n]
    x = np.column_stack([
        np.sin(np.arange(n) / 7.0),
        np.cos(np.arange(n) / 11.0),
        y.astype(float) * 0.02,
    ])
    return y, p, x, pt, mature


def test_current_case_and_same_prediction_time_are_excluded():
    y, p, x, pt, mature = fixture()
    pt[41] = pt[40]
    out = retrieval_local_prediction_sets(
        y, p, x, pt, mature, min_calibration=10, max_pool=40, k=10
    )
    assert out["pool_size"][41] == out["pool_size"][40]


def test_immature_outcome_is_excluded():
    y, p, x, pt, mature = fixture()
    mature[20] = pt[50]
    out = retrieval_local_prediction_sets(
        y, p, x, pt, mature, min_calibration=10, max_pool=50, k=10
    )
    expected = int(sum(pt[j] < pt[30] and mature[j] <= pt[30] for j in range(30)))
    assert out["pool_size"][30] == expected


def test_bounded_retrieval_and_determinism():
    y, p, x, pt, mature = fixture(100)
    a = retrieval_local_prediction_sets(
        y, p, x, pt, mature, min_calibration=10, max_pool=25, k=12
    )
    b = retrieval_local_prediction_sets(
        y, p, x, pt, mature, min_calibration=10, max_pool=25, k=12
    )
    assert a["pool_size"].max() <= 25
    assert a["retrieved_size"].max() <= 12
    assert np.array_equal(a["set_size"], b["set_size"])
    assert np.allclose(
        np.nan_to_num(a["pvalues"], nan=-1.0),
        np.nan_to_num(b["pvalues"], nan=-1.0),
    )


def test_unsorted_prediction_times_fail_closed():
    y, p, x, pt, mature = fixture(20)
    bad = list(pt)
    bad[5] = bad[4] - timedelta(minutes=1)
    with pytest.raises(ValueError, match="monotonically"):
        retrieval_local_prediction_sets(y, p, x, bad, mature)


def test_impossible_maturity_and_nonfinite_feature_fail_closed():
    y, p, x, pt, mature = fixture(20)
    bad_mature = list(mature)
    bad_mature[5] = pt[5] - timedelta(minutes=1)
    with pytest.raises(ValueError, match="cannot precede"):
        retrieval_local_prediction_sets(y, p, x, pt, bad_mature)
    x[5, 1] = np.nan
    with pytest.raises(ValueError, match="finite"):
        retrieval_local_prediction_sets(y, p, x, pt, mature)


def test_metrics_exclude_warmup():
    y, p, x, pt, mature = fixture(60)
    out = retrieval_local_prediction_sets(
        y, p, x, pt, mature, min_calibration=10, max_pool=30, k=10
    )
    metrics = retrieval_local_metrics(out, y)
    assert metrics["eligible_rows"] == 50.0
    assert np.isfinite(metrics["coverage_eligible"])
    assert 0.0 <= metrics["eligible_fraction"] <= 1.0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
