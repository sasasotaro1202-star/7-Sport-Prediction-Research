from __future__ import annotations

from src.online_fixed_share_hedge import FixedShareHedge, HedgeEvent, chronological_predictions


def test_initial_prediction_uses_baseline_only():
    m=FixedShareHedge(2,baseline_weights=[0.75,0.25])
    assert abs(m.predict([0.5,0.5])-0.5)<1e-12
    assert m.state()==[0.75,0.25]


def test_update_changes_weights_only_after_observation():
    m=FixedShareHedge(2,learning_rate=1.0,share=0.0)
    before=m.state()
    assert abs(m.predict([0.9,0.1])-0.5)<1e-12
    m.update([0.9,0.1],0)
    after=m.state()
    assert after[1]>before[1]


def test_same_timestamp_is_atomic():
    events=[
        HedgeEvent("a","2026-01-01T00:00:00Z",1,(0.9,0.1)),
        HedgeEvent("b","2026-01-01T00:00:00Z",0,(0.9,0.1)),
    ]
    preds=chronological_predictions(events)
    assert abs(preds[0][1]-0.5)<1e-12
    assert abs(preds[1][1]-0.5)<1e-12


def test_invalid_configuration_fails_closed():
    for kwargs in (
        {"n_experts":1},
        {"n_experts":2,"learning_rate":0},
        {"n_experts":2,"share":1.1},
    ):
        try:
            FixedShareHedge(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid configuration must fail closed")
