from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import numpy as np

from src import participant_context_features as pc
from src import feature_pattern_search as fps


def test_profile_numeric_parsing():
    assert abs(pc._coerce_numeric("height_cm", None, "5' 10\"") - 177.8) < 1e-6
    assert abs(pc._coerce_numeric("weight_kg", None, "170 lbs") - 77.1107029) < 1e-5
    assert abs(pc._coerce_numeric("reach_cm", None, '72"') - 182.88) < 1e-6


def test_pit_feature_cutoff():
    idx = {
        "p1": [
            (datetime(2025,1,1,tzinfo=timezone.utc).timestamp(),
             datetime(2025,1,2,tzinfo=timezone.utc).timestamp(),
             "height_cm", 180.0, None),
            (datetime(2025,2,1,tzinfo=timezone.utc).timestamp(),
             datetime(2025,2,2,tzinfo=timezone.utc).timestamp(),
             "height_cm", 181.0, None),
        ]
    }
    cutoff = datetime(2025,1,15,tzinfo=timezone.utc)
    got = pc.features_for(idx, "p1", cutoff)
    assert got["profile__height_cm"] == 180.0
    assert "profile__age_years" not in got


def _synthetic(n=360):
    rng=np.random.default_rng(7)
    x=rng.normal(size=(n,8))
    y=(0.8*x[:,0]-0.4*x[:,1]+0.25*x[:,5]+rng.normal(scale=0.8,size=n)>0).astype(int)
    names=[
      "A__elo","D__recent_form_delta","D__rest_days","D__opponent_elo_mean_20",
      "D__h2h_winrate_20","D__sig_str__mean","A__profile__height_cm","D__elo_x_form"
    ]
    return x,y,names


def test_pattern_search_is_deterministic_and_avoids_test_region():
    X,y,names=_synthetic()
    out1=fps.select_feature_pattern(X,y,names,"ufc",min_rows=240)
    out2=fps.select_feature_pattern(X,y,names,"ufc",min_rows=240)
    assert out1["status"]=="SELECTED"
    assert out1["selected_feature_names"]==out2["selected_feature_names"]
    assert out1["search_data_max_index"] < len(y)*0.50
    assert out1["main_oos_reserved_from_index"] >= out1["search_data_max_index"] + 1
    assert out1["holdout_access"] is False
