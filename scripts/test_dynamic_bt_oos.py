from __future__ import annotations

from src.dynamic_bt_oos import BTEvent, ShockAdaptiveBT, chronological_predictions


def test_no_lookahead_first_event_is_prior():
    events = [
        BTEvent("e2", "2026-01-02T00:00:00Z", "A", "B", 0),
        BTEvent("e1", "2026-01-01T00:00:00Z", "A", "B", 1),
    ]
    preds = chronological_predictions(events)
    assert preds[0][0].event_id == "e1"
    assert abs(preds[0][1] - 0.5) < 1e-12


def test_surprise_triggers_higher_adaptation():
    model_calm = ShockAdaptiveBT()
    model_shock = ShockAdaptiveBT()
    for _ in range(12):
        model_calm.update("A", "B", 1)
        model_shock.update("A", "B", 1)

    # A strong prior should normally make A-vs-B close to certain. A B win is
    # therefore an explicit surprise and should invoke a larger process variance.
    p = model_shock.predict_event("A", "B")
    info = model_shock.update("A", "B", 0)
    assert p > 0.5
    assert info["shock_probability"] > 0.5
    assert info["process_variance"] > model_calm.stable_process_var


def test_invalid_participants_fail_closed():
    model = ShockAdaptiveBT()
    try:
        model.predict_event("A", "A")
    except ValueError:
        pass
    else:
        raise AssertionError("same participant IDs must fail closed")


def test_same_timestamp_predictions_do_not_consume_same_block_outcomes():
    events = [
        BTEvent("a", "2026-01-01T00:00:00Z", "A", "B", 1),
        BTEvent("b", "2026-01-01T00:00:00Z", "A", "C", 1),
    ]
    preds = chronological_predictions(events)
    assert abs(preds[0][1] - 0.5) < 1e-12
    assert abs(preds[1][1] - 0.5) < 1e-12
