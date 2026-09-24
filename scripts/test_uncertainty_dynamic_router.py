from __future__ import annotations

import numpy as np

from src.uncertainty_dynamic_router_oos import (
    expert_voi_targets,
    predictive_entropy,
    population_drift_features,
    bootstrap_clustered_improvement,
    route_uncertainty_score,
    temporal_recalibration,
    uncertainty_features,
)


def main() -> None:
    bp = np.asarray([
        [0.49, 0.50, 0.51],
        [0.20, 0.80, 0.50],
    ])
    ctx = np.zeros((2, 10), dtype=float)
    u = uncertainty_features(bp, ctx)
    assert u.shape == (2, 10)
    assert np.all(np.isfinite(u))
    assert predictive_entropy(np.asarray([0.5]))[0] > predictive_entropy(np.asarray([0.9]))[0]

    ref = np.asarray([[0.0, 1.0, 0.5], [0.1, 0.9, 0.4], [0.0, 1.0, np.nan]])
    cur = np.asarray([[2.0, 1.0, 0.5], [2.1, 0.9, 0.4], [2.0, 1.0, np.nan]])
    drift = population_drift_features(ref, cur)
    assert drift.shape == (3,)
    assert np.all(np.isfinite(drift)) and np.all((drift >= 0.0) & (drift <= 1.0))
    assert drift[0] > 0.0 and drift[2] > 0.0

    repeated = bootstrap_clustered_improvement(
        [np.asarray([-.02, -.02, .10, .10]), np.asarray([-.03, -.03, .08, .08])],
        [np.asarray(["g1", "g1", "g2", "g2"], dtype=object), np.asarray(["g3", "g3", "g4", "g4"], dtype=object)],
        draws=400,
    )
    assert repeated["clusters"] == 4
    assert 0.0 <= repeated["probability_improvement"] <= 1.0

    loss_equal = np.zeros_like(bp)
    p = route_uncertainty_score(loss_equal, bp, ctx)
    assert np.allclose(p, np.mean(bp, axis=1), atol=1e-9), p

    loss_sep = np.asarray([
        [0.20, 0.80, 0.81],
        [0.80, 0.20, 0.82],
    ])
    routed = route_uncertainty_score(loss_sep, bp, ctx)
    assert np.all(np.isfinite(routed))

    voi = np.asarray([
        [0.020, -0.005, 0.000],
        [-0.002, 0.030, 0.001],
    ])
    routed_voi = route_uncertainty_score(loss_sep, bp, ctx, predicted_voi=voi)
    assert np.all(np.isfinite(routed_voi))
    assert np.all((routed_voi > 0.0) & (routed_voi < 1.0))

    y_small = np.asarray([0, 1, 0, 1, 0, 1])
    bp_small = np.asarray([
        [0.40, 0.55, 0.45],
        [0.70, 0.40, 0.55],
        [0.35, 0.60, 0.50],
        [0.65, 0.45, 0.55],
        [0.45, 0.65, 0.50],
        [0.60, 0.40, 0.55],
    ])
    baseline_small = np.mean(bp_small, axis=1)
    targets = expert_voi_targets(bp_small, y_small, baseline_small)
    assert targets.shape == bp_small.shape
    assert np.all(np.isfinite(targets))

    rng = np.random.default_rng(42)
    y = (rng.random(360) > 0.5).astype(int)
    raw = np.clip(0.15 + 0.70 * rng.random(360), 1e-5, 1-1e-5)
    groups = np.repeat(np.arange(120), 3)
    cal = temporal_recalibration(raw, y, groups)
    assert isinstance(cal, dict)
    assert "accepted" in cal
    if cal["accepted"]:
        assert cal["bootstrap"]["probability_improvement"] >= 0.90
        assert cal["bootstrap"]["p05_improvement"] > 0.0
    print("UNCERTAINTY_ROUTER_OOS_SMOKE=PASS")


if __name__ == "__main__":
    main()
