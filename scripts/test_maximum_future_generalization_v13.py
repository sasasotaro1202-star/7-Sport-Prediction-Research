from __future__ import annotations

import unittest
import numpy as np

from src.maximum_future_generalization_v13 import (
    _compute_tier,
    _output_format,
    _ood_score,
    _scenario,
    _future_trajectory,
    _select_strategy,
    run_control_layer,
)


class MaximumFutureGeneralizationV13Tests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(13)
        self.n = 420
        self.x = rng.normal(size=(self.n, 8))
        latent = 0.9 * self.x[:, 0] - 0.45 * self.x[:, 1] + rng.normal(scale=0.8, size=self.n)
        self.y = (latent > 0).astype(int)
        self.bp = np.column_stack([
            np.clip(1.0 / (1.0 + np.exp(-(0.85 * latent + 0.25 * rng.normal(size=self.n)))), 0.02, 0.98),
            np.clip(1.0 / (1.0 + np.exp(-(0.65 * latent + 0.35 * rng.normal(size=self.n)))), 0.02, 0.98),
            np.clip(1.0 / (1.0 + np.exp(-(0.50 * latent + 0.45 * rng.normal(size=self.n)))), 0.02, 0.98),
        ])

    def test_scenario_is_normalized(self):
        row = _scenario(0.62, 0.35, 0.20, 0.25)
        self.assertEqual(row["labels"], ["NORMAL", "SHOCK", "REVERSAL"])
        self.assertAlmostEqual(sum(row["probabilities"]), 1.0, places=10)

    def test_ood_is_pre_row_only(self):
        a = _ood_score(self.x)
        mutated = self.x.copy()
        mutated[220:] += 100.0
        b = _ood_score(mutated)
        np.testing.assert_allclose(a[:220], b[:220], rtol=0, atol=1e-12)

    def test_output_and_compute_policies(self):
        q = np.array([0.9, 0.5, 0.1])
        u = np.array([0.1, 0.6, 0.9])
        f = np.array([0.1, 0.3, 0.9])
        o = np.array([0.1, 0.4, 0.9])
        self.assertEqual(_compute_tier(q, u, f, o), ["STANDARD", "ENSEMBLE_PLUS_RETRIEVAL", "ABSTAIN_OR_FALLBACK"])
        self.assertEqual(_output_format(q, u, o), ["PROBABILITY", "PROBABILITY_RANGE", "ABSTAIN"])

    def test_strategy_selection_is_prior_only(self):
        pred = {"A": self.bp[:, 0], "B": self.bp[:, 1], "C": self.bp[:, 2]}
        q = np.full(self.n, 0.7)
        u = np.full(self.n, 0.2)
        f = np.full(self.n, 0.2)
        o = np.full(self.n, 0.1)
        d = np.std(self.bp, axis=1)
        s = np.ones(self.n)
        sel_a, _, _ = _select_strategy(pred, q, u, f, o, d, s, self.y)
        y2 = self.y.copy()
        y2[300:] = 1 - y2[300:]
        sel_b, _, _ = _select_strategy(pred, q, u, f, o, d, s, y2)
        self.assertEqual(sel_a[:300], sel_b[:300])

    def test_future_trajectory_enforces_horizon_embargo(self):
        features = np.column_stack([self.x, self.bp])
        out, audit = _future_trajectory(features, self.y, horizons=(1, 3))
        self.assertEqual(out.shape, (self.n, 2))
        self.assertTrue(any(v["future_label_embargo_enforced"] for v in audit["audits"].values()))

    def test_full_control_layer_contract(self):
        reliability = np.clip(0.7 + 0.1 * self.x[:, 0], 0.0, 1.0)
        source = np.clip(0.8 + 0.1 * self.x[:, 1], 0.0, 1.0)
        drift = np.column_stack([
            np.clip(np.abs(self.x[:, 2]), 0, 3), self.x[:, 3], self.x[:, 4], np.clip(np.abs(self.x[:, 5]), 0, 1)
        ])
        unc = {
            "data_uncertainty": np.clip(1 - reliability, 0, 1),
            "model_uncertainty": np.std(self.bp, axis=1),
            "distribution_shift_uncertainty": np.clip(drift[:,0] / 3, 0, 1),
            "information_uncertainty": np.clip(1 - source, 0, 1),
        }
        failure = np.column_stack([
            np.clip(0.25 + 0.10*np.abs(self.x[:, 0]), 0, 1),
            np.clip(0.30 + 0.10*np.abs(self.x[:, 1]), 0, 1),
            np.clip(0.35 + 0.10*np.abs(self.x[:, 2]), 0, 1),
        ])
        result = run_control_layer(
            sport="synthetic",
            x=self.x,
            y=self.y,
            base_probabilities=self.bp,
            baseline=np.average(self.bp, axis=1, weights=[0.45,0.35,0.20]),
            dynamic=np.mean(self.bp, axis=1),
            retrieval_success=np.clip(0.5 + 0.2*self.x[:,0], 0.05, 0.95),
            meta_reliability=np.clip(0.5 + 0.2*self.x[:,1], 0.05, 0.95),
            predictability=np.clip(0.75 - 0.15*np.std(self.bp, axis=1), 0, 1),
            failure_risk=failure,
            uncertainty_matrix=unc,
            feature_reliability=reliability,
            source_reliability=source,
            disagreement=np.std(self.bp, axis=1),
            drift=drift,
            event_ids=[f"e{i}" for i in range(self.n)],
            feature_names=[f"f{i}" for i in range(self.x.shape[1])],
            model_names=["m1","m2","m3"],
            model_version="v13-test-model",
            dataset_hash="v13-test",
            feature_version="v13-test-features",
        )
        self.assertEqual(result["v13"]["status"], "EVALUATED")
        self.assertFalse(result["v13"]["production_changed"])
        self.assertEqual(result["v13"]["promotion"], "HOLD")
        for key in (
            "prediction_policy", "dynamic_prediction", "prediction_output",
            "adaptive_compute", "active_information", "prediction_history",
            "future_trajectory", "prediction_lifetime", "novelty_ood",
            "error_attribution", "prediction_contract", "model_portfolio",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["prediction_contract"]["data_snapshot"]["dataset_hash"], "v13-test")
        self.assertEqual(len(result["prediction_history"]["rows"]), self.n)
        self.assertEqual(len(result["prediction_output"]["scenarios"]), self.n)
        self.assertEqual(result["active_information"]["status"], "RESEARCH_PROXY_NO_EXTERNAL_CALL")


if __name__ == "__main__":
    unittest.main()
