from __future__ import annotations

import numpy as np

from src.dynamic_model_router import _route_with_contextual_loss_selector, predict_with_router


class _ConstantPredictor:
    def predict(self, X):
        return np.zeros(len(X), dtype=float)


def main() -> None:
    bp = np.asarray([[0.20, 0.80]], dtype=float)
    ctx = np.zeros((1, 10), dtype=float)
    selector = {
        "kind": "contextual_loss_v1",
        "selectors": [_ConstantPredictor(), _ConstantPredictor()],
        "model_names": ["a", "b"],
        "baseline_weights": {"a": 0.10, "b": 0.90},
        "loss_spread_scale": 0.05,
    }

    routed = _route_with_contextual_loss_selector(selector, bp, ctx, np.zeros(2))
    expected_weighted_baseline = 0.20 * 0.10 + 0.80 * 0.90
    # Zero predicted loss separation should suppress routing and return the
    # exact incumbent baseline, avoiding arbitrary regime switching.
    assert np.isclose(routed[0], expected_weighted_baseline), (routed[0], expected_weighted_baseline)

    legacy = dict(selector)
    legacy.pop("baseline_weights")
    legacy_result = _route_with_contextual_loss_selector(legacy, bp, ctx, np.zeros(2))
    assert np.isclose(legacy_result[0], 0.50), legacy_result


    class _Base:
        def __init__(self, p):
            self.p = p

        def predict_proba(self, X):
            return np.column_stack([1.0-np.full(len(X), self.p), np.full(len(X), self.p)])

    fallback, meta = predict_with_router(
        None,
        [_Base(0.20), _Base(0.80)],
        ["a", "b"],
        np.zeros((2, 1)),
        np.zeros((1, 1)),
        baseline_weights={"a": 0.10, "b": 0.90},
    )
    assert meta["fallback"] is True
    assert np.isclose(fallback[0], expected_weighted_baseline), fallback

    print("ROUTER_INCUMBENT_BASELINE_ALIGNMENT=PASS")


if __name__ == "__main__":
    main()
