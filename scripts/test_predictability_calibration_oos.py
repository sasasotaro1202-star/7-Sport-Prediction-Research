from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.predictability_calibration_oos import (
    brier,
    chronological_predictability_calibration,
    ece,
)


def _fixture(n=180):
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    pt=[(base+timedelta(hours=i)).isoformat() for i in range(n)]
    mt=[(base+timedelta(hours=i,minutes=30)).isoformat() for i in range(n)]
    raw=np.linspace(0.1,0.9,n)
    correctness=(raw>0.52).astype(int)
    return raw,correctness,pt,mt


def test_frozen_locked_calibrator_ignores_locked_outcomes():
    raw,y,pt,mt=_fixture()
    out_a=chronological_predictability_calibration(raw,y,pt,mt,locked_start=140,min_history=30,max_history=80)
    changed=y.copy()
    changed[140:]=1-changed[140:]
    out_b=chronological_predictability_calibration(raw,changed,pt,mt,locked_start=140,min_history=30,max_history=80)
    assert np.allclose(out_a["calibrated"][140:],out_b["calibrated"][140:])
    assert out_a["contract"]["locked_outcomes_update_calibrator"] is False
    assert out_a["frozen_training_rows"] == out_b["frozen_training_rows"]


def test_same_time_and_immature_history_are_excluded():
    raw,y,pt,mt=_fixture(160)
    pt[50]=pt[49]
    mt[50]=(datetime(2026,1,5,tzinfo=timezone.utc)).isoformat()
    out=chronological_predictability_calibration(raw,y,pt,mt,locked_start=130,min_history=20,max_history=60)
    assert out["training_rows_by_row"][51] == 50
    assert out["contract"]["same_prediction_time_excluded"] is True


def test_invalid_range_fails_closed():
    raw,y,pt,mt=_fixture(140)
    raw[0]=1.2
    with pytest.raises(ValueError,match="\[0,1\]"):
        chronological_predictability_calibration(raw,y,pt,mt,locked_start=100,min_history=20)


def test_metrics_are_bounded():
    y=np.array([0,1,1,0])
    p=np.array([0.2,0.7,0.8,0.1])
    assert 0.0 <= brier(y,p) <= 1.0
    assert 0.0 <= ece(y,p) <= 1.0
