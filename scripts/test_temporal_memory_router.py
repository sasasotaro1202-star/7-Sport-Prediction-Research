from __future__ import annotations

import numpy as np

from src import dynamic_model_router as router


def _synthetic_folds():
    names = ["a", "b"]
    folds = []
    rng = np.random.default_rng(7)
    for i in range(7):
        n = 30
        end = i * n
        te = end + n
        y = ((np.arange(7 * n) + 1) % 2).astype(int)
        # Expert A is better in even folds; expert B in odd folds.
        ya = y[end:te].astype(float)
        noise = rng.normal(0.0, 0.04, size=n)
        if i % 2 == 0:
            pa = np.clip(0.5 + 0.35 * (1.0 - 2.0 * ya) * -1.0 + noise, 0.02, 0.98)
            pb = np.clip(0.5 + 0.20 * (1.0 - 2.0 * ya) * -1.0 + noise, 0.02, 0.98)
        else:
            pa = np.clip(0.5 + 0.20 * (1.0 - 2.0 * ya) * -1.0 + noise, 0.02, 0.98)
            pb = np.clip(0.5 + 0.35 * (1.0 - 2.0 * ya) * -1.0 + noise, 0.02, 0.98)
        # Explicit feature matrix is used only to construct row-local context.
        folds.append({
            "end": end,
            "te": te,
            "preds": {"a": pa.tolist(), "b": pb.tolist()},
        })
    return y, folds


def test_temporal_memory_requires_history_before_routing():
    y, folds = _synthetic_folds()
    result = router.evaluate_temporal_memory_router_from_folds(
        np.zeros((len(y), 3), dtype=float),
        y,
        ["a", "b"],
        folds,
        {"a": 0.5, "b": 0.5},
    )
    assert result["status"] == "EVALUATED"
    assert result["policy"].startswith("research_only;")
    assert result["folds"] == len(folds)
    assert result["oos_rows"] == sum(f["te"] - f["end"] for f in folds)


def test_temporal_memory_is_conservative_and_bounded():
    y, folds = _synthetic_folds()
    result = router.evaluate_temporal_memory_router_from_folds(
        np.zeros((len(y), 3), dtype=float),
        y,
        ["a", "b"],
        folds,
        {"a": 0.7, "b": 0.3},
    )
    assert result["status"] == "EVALUATED"
    assert 0.0 <= result["mean_route_strength"] <= 0.65
    assert result["p95_nearest_distance"] is not None
    assert np.isfinite(result["p95_nearest_distance"])


def test_holdout_uses_pre_holdout_memory_only():
    y, folds = _synthetic_folds()
    holdout_pred = {
        "a": np.full(30, 0.6, dtype=float),
        "b": np.full(30, 0.4, dtype=float),
    }
    holdout_X = np.zeros((30, 3), dtype=float)
    result = router.evaluate_frozen_holdout_temporal_memory_router_from_folds(
        np.zeros((len(y), 3), dtype=float),
        y,
        ["a", "b"],
        folds,
        holdout_pred,
        holdout_X,
        np.asarray([0, 1] * 15),
        {"a": 0.5, "b": 0.5},
    )
    assert result["status"] == "EVALUATED"
    assert result["policy"].startswith("research_only; pre-holdout OOF memory only")


if __name__ == "__main__":
    test_temporal_memory_requires_history_before_routing()
    test_temporal_memory_is_conservative_and_bounded()
    test_holdout_uses_pre_holdout_memory_only()
    print("temporal memory router tests passed")
