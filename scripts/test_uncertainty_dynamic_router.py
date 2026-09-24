from __future__ import annotations

import numpy as np

from src.uncertainty_dynamic_router_oos import (
    predictive_entropy,
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

    loss_equal = np.zeros_like(bp)
    p = route_uncertainty_score(loss_equal, bp, ctx)
    assert np.allclose(p, np.mean(bp, axis=1), atol=1e-9), p

    loss_sep = np.asarray([
        [0.20, 0.80, 0.81],
        [0.80, 0.20, 0.82],
    ])
    routed = route_uncertainty_score(loss_sep, bp, ctx)
    assert np.all(np.isfinite(routed))

    rng = np.random.default_rng(42)
    y = (rng.random(240) > 0.5).astype(int)
    raw = np.clip(0.15 + 0.70 * rng.random(240), 1e-5, 1-1e-5)
    cal = temporal_recalibration(raw, y)
    assert isinstance(cal, dict)
    assert "accepted" in cal
    print("UNCERTAINTY_ROUTER_OOS_SMOKE=PASS")


if __name__ == "__main__":
    main()
