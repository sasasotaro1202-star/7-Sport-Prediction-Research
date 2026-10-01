from datetime import datetime, timedelta, timezone
import numpy as np
import pytest
from src.conformal_set_aggregation import block_coverage_metrics, online_aggregate, weighted_vote_set

def fixture(n=8):
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    pt=[base+timedelta(hours=i) for i in range(n)]
    mature=[t+timedelta(hours=1) for t in pt]
    outcomes=[0,1,0,1,0,1,0,1][:n]
    a=[[0] if i%2==0 else [1] for i in range(n)]
    b=[[0,1] for _ in range(n)]
    return [a,b],outcomes,pt,mature

def test_weighted_vote():
    sets=[[[0],[1]], [[1],[1]]]
    assert weighted_vote_set(sets,[0.75,0.25],min_vote=0.5)==[[0],[1]]
    assert weighted_vote_set(sets,[0.25,0.75],min_vote=0.5)==[[1],[1]]

def test_maturity_gated_update_does_not_use_same_case():
    sets,y,pt,mature=fixture(8)
    mature[0]=pt[7]
    out=online_aggregate(sets,y,pt,mature,min_calibration=1)
    assert out["calibration_counts"][1]==0
    assert out["eligible_flags"][1] is False
    assert out["coverage_guarantee_claimed"] is False

def test_same_prediction_time_is_excluded():
    sets,y,pt,mature=fixture(8)
    pt[4]=pt[3]
    out=online_aggregate(sets,y,pt,mature,min_calibration=0)
    assert out["calibration_counts"][4] < 4
    assert out["eligible_flags"][0] is False

def test_prediction_time_must_have_timezone():
    sets,y,pt,mature=fixture(3)
    pt[1]=pt[1].replace(tzinfo=None)
    with pytest.raises(ValueError,match="timezone-aware"):
        online_aggregate(sets,y,pt,mature)

def test_weights_remain_finite_and_normalized():
    sets,y,pt,mature=fixture(8)
    out=online_aggregate(sets,y,pt,mature,min_calibration=1,learning_rate=0.5)
    assert np.isfinite(out["final_weights"]).all()
    assert np.isclose(sum(out["final_weights"]),1.0)
    assert all(np.isclose(sum(w),1.0) for w in out["weight_history"])


def test_invalid_weights_fail_closed():
    sets, y, pt, mature = fixture(8)
    with pytest.raises(ValueError, match="weights must be finite"):
        weighted_vote_set(sets, [float("nan"), 1.0])

def test_eligible_coverage_excludes_warmup():
    sets, y, pt, mature = fixture(8)
    out = online_aggregate(sets, y, pt, mature, min_calibration=3)
    assert out["eligible_rows"] == 5
    assert np.isfinite(out["coverage_eligible"])


def test_block_coverage_is_chronological_and_descriptive():
    sets = [[0], [0], [1], [1], [0], [1], [1], [0]]
    y = [0, 1, 1, 0, 0, 1, 0, 0]
    report = block_coverage_metrics(sets, y, blocks=4)
    assert report["rows"] == 8
    assert report["blocks"] == 4
    assert report["overall_coverage"] == 0.625
    assert report["worst_block_coverage"] == 0.5
    assert report["max_undercoverage"] == 0.125
    assert report["guarantee_claimed"] is False
