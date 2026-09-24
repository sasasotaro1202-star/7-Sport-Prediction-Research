from __future__ import annotations

import numpy as np

from src.uncertainty_dynamic_router_oos import (
    expert_voi_targets,
    predictive_entropy,
    fit_uncertainty_loss_selector,
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
        [
            np.asarray([-.02, -.02, -.01, .10, .10, .08, .05, .05, .02, .02]),
            np.asarray([-.03, -.03, -.02, .08, .08, .06, .04, .04, .01, .01]),
        ],
        [
            np.asarray(["g1", "g1", "g2", "g2", "g3", "g3", "g4", "g4", "g5", "g5"], dtype=object),
            np.asarray(["g6", "g6", "g7", "g7", "g8", "g8", "g9", "g9", "g10", "g10"], dtype=object),
        ],
        draws=400,
    )
    assert repeated["clusters"] == 10
    assert 0.0 <= repeated["probability_improvement"] <= 1.0

    loss_equal = np.zeros_like(bp)
    p = route_uncertainty_score(loss_equal, bp, ctx)
    assert np.allclose(p, np.mean(bp, axis=1), atol=1e-9), p

    # Constant meta columns are common with sparse matchday contexts. The
    # selector must drop them instead of allowing HGB's binning to fail.
    X_meta = np.column_stack([
        np.linspace(0.0, 1.0, 140),
        np.ones(140),
        np.zeros(140),
        np.repeat([0.0, 1.0], 70),
    ])
    L_meta = np.column_stack([
        0.5 + 0.05 * np.sin(np.linspace(0.0, 4.0, 140)),
        0.6 + 0.04 * np.cos(np.linspace(0.0, 4.0, 140)),
        0.7 + 0.03 * np.sin(np.linspace(0.0, 8.0, 140)),
    ])
    V_meta = L_meta - 0.01
    guarded = fit_uncertainty_loss_selector(
        X_meta, L_meta, ["a", "b", "c"], V_meta
    )
    assert guarded is not None
    mask = np.asarray(guarded["feature_mask"], dtype=bool)
    assert mask.shape == (4,) and mask.tolist() == [True, False, False, True]

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
