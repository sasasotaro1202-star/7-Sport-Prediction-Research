from src.matchday_horizon_eval import (
    HORIZONS,
    _candidate_pipeline,
    _safe_logit,
    _with_context,
    _bootstrap_oos,
)

import numpy as np


def main():
    assert HORIZONS == (1440, 360, 90, 60)

    p = np.array([0.2, 0.8, 0.6, 0.4], dtype=float)
    assert np.allclose(_safe_logit(p), np.log(p / (1.0 - p)))

    ctx = np.array(
        [
            [1.0, np.nan, 0.5],
            [0.0, 0.2, np.nan],
            [-1.0, 0.0, 0.1],
            [np.nan, np.nan, np.nan],
        ]
    )
    X = _with_context(p, ctx)
    assert X.shape == (4, 4)
    assert np.isfinite(X[:, 0]).all()

    y = np.array([0, 1, 1, 0] * 80)
    rng = np.random.default_rng(9)
    base_p = np.clip(0.15 + 0.7 * rng.random(len(y)), 1e-6, 1 - 1e-6)
    cctx = rng.normal(size=(len(y), 3))
    model = _candidate_pipeline()
    model.fit(_with_context(base_p[:200], cctx[:200]), y[:200])
    pred = model.predict_proba(_with_context(base_p[200:], cctx[200:]))[:, 1]
    assert pred.shape == (len(y) - 200,)
    assert np.isfinite(pred).all()

    deltas = [rng.normal(0, 0.01, size=80) for _ in range(6)]
    groups = [np.array([f"e{i}" for i in range(80)], dtype=object) for _ in range(6)]
    boot = _bootstrap_oos(deltas, groups)
    assert {"probability_improvement", "p05_improvement", "clusters"} <= set(boot)
    assert boot["clusters"] >= 30

    print("MATCHDAY_HORIZON_EVAL=PASS")


if __name__ == "__main__":
    main()
