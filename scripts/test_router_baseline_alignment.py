from __future__ import annotations

import numpy as np

from src.dynamic_model_router import _route_with_contextual_loss_selector


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
    }

    routed = _route_with_contextual_loss_selector(selector, bp, ctx, np.zeros(2))
    expected_weighted_baseline = 0.20 * 0.10 + 0.80 * 0.90
    expected = 0.75 * 0.50 + 0.25 * expected_weighted_baseline
    assert np.isclose(routed[0], expected), (routed[0], expected)

    legacy = dict(selector)
    legacy.pop("baseline_weights")
    legacy_result = _route_with_contextual_loss_selector(legacy, bp, ctx, np.zeros(2))
    assert np.isclose(legacy_result[0], 0.50), legacy_result

    print("ROUTER_INCURMBENT_BASELINE_ALIGNMENT=PASS")


if __name__ == "__main__":
    main()
