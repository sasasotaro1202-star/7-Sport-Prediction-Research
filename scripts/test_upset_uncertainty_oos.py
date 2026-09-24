from __future__ import annotations

import numpy as np

from src.upset_uncertainty_oos import (
    _feature_matrix,
    _policy_probability,
    _risk_target,
)


def test_risk_target_only_marks_high_confidence_misses():
    p = np.asarray([0.90, 0.85, 0.60, 0.40, 0.10])
    y = np.asarray([1, 0, 0, 1, 0])
    target = _risk_target(p, y)
    assert target.tolist() == [1, 0, 0, 0, 0]


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


def test_feature_matrix_preserves_nan_context():
    p = np.asarray([0.8, 0.2])
    ep = np.asarray([[0.8, 0.7], [0.2, 0.4]])
    ctx = np.asarray([[np.nan, 1.0], [0.0, np.nan]])
    X = np.asarray([[1.0, np.nan], [2.0, 3.0]])
    f = _feature_matrix(p, ep, ctx, X)
    assert f.shape == (2, 10 + 2 + 2)
    assert np.isnan(f[0, 10])
    assert np.isnan(f[1, 11])


if __name__ == "__main__":
    test_risk_target_only_marks_high_confidence_misses()
    test_policy_shrinkage_respects_risk_and_confidence_gates()
    test_policy_shrinkage_is_toward_half_and_bounded()
    test_feature_matrix_preserves_nan_context()
