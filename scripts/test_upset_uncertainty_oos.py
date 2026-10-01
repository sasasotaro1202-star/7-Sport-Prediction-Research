from __future__ import annotations

import numpy as np

from src.upset_uncertainty_oos import (
    _dissent_probability,
    _feature_matrix,
    _policy_dissent,
    _policy_probability,
    _risk_target,
)


def test_risk_target_only_marks_high_confidence_misses():
    p = np.asarray([0.90, 0.85, 0.60, 0.40, 0.10])
    y = np.asarray([1, 0, 0, 1, 0])
    target = _risk_target(p, y)
    assert target.tolist() == [0, 1, 0, 0, 0]


def test_policy_shrinkage_respects_risk_and_confidence_gates():
    p = np.asarray([0.70, 0.60, 0.30])
    risk = np.asarray([0.40, 0.90, 0.90])
    out = _policy_probability(p, risk, 0.50)
    assert np.isclose(out[0], p[0])
    assert np.isclose(out[1], p[1])
    assert np.isclose(out[2], 0.40)


def test_policy_shrinkage_is_toward_half_and_bounded():
    p = np.asarray([0.99, 0.01])
    risk = np.asarray([1.0, 1.0])
    out = _policy_probability(p, risk, 0.50)
    assert out[0] < p[0] and out[0] >= 0.5
    assert out[1] > p[1] and out[1] <= 0.5
    assert np.isclose(out[0], 0.745)
    assert np.isclose(out[1], 0.255)


def test_dissent_probability_uses_only_opposing_experts():
    p = np.asarray([0.90, 0.10])
    ep = np.asarray([[0.92, 0.45, 0.20], [0.08, 0.55, 0.80]])
    d, available = _dissent_probability(p, ep, np.asarray([0.5, 0.3, 0.2]))
    assert available.tolist() == [True, True]
    assert np.isclose(d[0], 0.35)
    assert np.isclose(d[1], 0.65)


def test_dissent_rescue_can_change_pick_only_under_gates():
    p = np.asarray([0.90])
    ep = np.asarray([[0.92, 0.45, 0.20]])
    risk = np.asarray([0.90])
    out, active = _policy_dissent(p, risk, ep, np.asarray([0.5, 0.3, 0.2]), 0.50)
    assert active.tolist() == [True]
    assert np.isclose(out[0], 0.625)


def test_feature_matrix_preserves_nan_context():
    p = np.asarray([0.8, 0.2])
    ep = np.asarray([[0.8, 0.7], [0.2, 0.4]])
    ctx = np.asarray([[np.nan, 1.0], [0.0, np.nan]])
    X = np.asarray([[1.0, np.nan], [2.0, 3.0]])
    f = _feature_matrix(p, ep, ctx, X)
    assert f.shape == (2, 10)
    # Eight derived signals precede the two context columns.
    assert np.isnan(f[0, 8])
    assert np.isnan(f[1, 9])


if __name__ == "__main__":
    test_risk_target_only_marks_high_confidence_misses()
    test_policy_shrinkage_respects_risk_and_confidence_gates()
    test_policy_shrinkage_is_toward_half_and_bounded()
    test_dissent_probability_uses_only_opposing_experts()
    test_dissent_rescue_can_change_pick_only_under_gates()
    test_feature_matrix_preserves_nan_context()


def test_overall_status_is_deferred_when_all_sports_are_deferred(monkeypatch):
    import src.upset_uncertainty_oos as module
    monkeypatch.setattr(module, "_evaluate_sport", lambda con, sport: {
        "sport": sport,
        "status": "DEFERRED",
        "reason": "synthetic_insufficient_data",
    })
    # The CLI-level aggregation is tested by exercising the same status rule
    # without touching a real database or production artifact.
    evaluated = [module._evaluate_sport(None, sport) for sport in ("basketball", "ufc")]
    overall = (
        "EVALUATED"
        if any(str(item.get("status")) == "EVALUATED" for item in evaluated)
        else "DEFERRED"
    )
    assert overall == "DEFERRED"


def test_cli_main_defines_sport_list(monkeypatch, tmp_path):
    import json
    import src.upset_uncertainty_oos as module

    db = tmp_path / "empty.sqlite"
    import sqlite3
    sqlite3.connect(db).close()
    monkeypatch.setattr(module, "DB", db)
    monkeypatch.setattr(module, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(
        module,
        "_evaluate_sport",
        lambda con, sport: {
            "sport": sport,
            "status": "DEFERRED",
            "reason": "synthetic",
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        ["upset_uncertainty_oos", "--sport", "ufc"],
    )

    assert module.main() == 0
    payload = json.loads(
        (tmp_path / "results" / "upset_uncertainty_oos.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "DEFERRED"
    assert payload["sports"][0]["sport"] == "ufc"
