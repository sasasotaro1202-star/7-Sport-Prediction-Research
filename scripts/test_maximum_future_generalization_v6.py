from __future__ import annotations

import unittest
import numpy as np

from src.maximum_future_generalization_v6 import (
    _error_correlation,
    _prediction_dynamics,
    _feature_reliability,
    _regime_transition,
    _retrieval_features,
    _uncertainty_decomposition,
    _sequential_tta,
    _conformal_binary,
    _adaptive_compute,
    _rolling_diversity_weights,
    _time_to_failure_predictor,
    _latent_state_proxy,
    _robustness_matrix,
    run_experiment,
)


class MaximumFutureGeneralizationV6Tests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(20260926)
        self.n = 720
        self.x = rng.normal(size=(self.n, 10))
        latent = 0.8 * self.x[:, 0] - 0.5 * self.x[:, 1] + rng.normal(scale=0.8, size=self.n)
        self.y = (latent > 0).astype(int)
        p1 = 1 / (1 + np.exp(-(0.9 * latent + 0.2 * rng.normal(size=self.n))))
        p2 = 1 / (1 + np.exp(-(0.7 * latent + 0.3 * rng.normal(size=self.n))))
        p3 = 1 / (1 + np.exp(-(0.5 * latent + 0.4 * rng.normal(size=self.n))))
        self.bp = np.column_stack([p1, p2, p3]).clip(0.01, 0.99)
        self.names = ["m1", "m2", "m3"]
        self.folds = []
        for end in range(60, 660, 60):
            te = min(end + 60, self.n)
            self.folds.append({
                "end": end, "te": te,
                "preds": {name: self.bp[end:te, j].tolist() for j, name in enumerate(self.names)},
                "event_ids": [f"e{i}" for i in range(end, te)],
            })

    def test_error_diversity_and_dynamics(self):
        out = _error_correlation(self.bp, self.y)
        self.assertEqual(len(out["model_error_rate"]), 3)
        dyn = _prediction_dynamics(self.bp)
        self.assertGreaterEqual(dyn["flip_count"], 0)
        self.assertTrue(np.isfinite(dyn["mean_velocity"]))

    def test_feature_reliability_is_rowwise(self):
        out = _feature_reliability(self.x)
        self.assertEqual(out["row_reliability"].shape, (self.n,))
        self.assertTrue(np.isfinite(out["row_reliability"]).all())
        self.assertTrue(((out["row_reliability"] >= 0) & (out["row_reliability"] <= 1)).all())

    def test_regime_transition_is_prequential(self):
        probs, meta = _regime_transition(self.x, self.bp)
        self.assertEqual(probs.shape, (self.n, 4))
        self.assertTrue(np.isfinite(probs).all())
        self.assertTrue(np.allclose(probs.sum(axis=1), 1.0))
        self.assertEqual(meta["threshold_policy"], "q70/q85/q95 recomputed from rows strictly before each evaluation row")

    def test_retrieval_is_prior_only(self):
        out, meta = _retrieval_features(self.x, self.bp, self.y)
        self.assertEqual(out.shape, (self.n, 5))
        self.assertEqual(meta["status"], "EVALUATED")
        self.assertTrue(np.isfinite(out[100:]).all())

    def test_tta_conformal_and_sequential_weights(self):
        baseline = self.bp @ np.array([0.5, 0.3, 0.2])
        tta = _sequential_tta(self.y, baseline, refit_interval=20)
        self.assertTrue(np.isfinite(tta).all())
        conf = _conformal_binary(self.y, baseline)
        self.assertEqual(conf["status"], "EVALUATED")
        w = _rolling_diversity_weights(self.bp, self.y, 200, np.array([0.5, 0.3, 0.2]))
        self.assertTrue(np.isclose(w.sum(), 1.0))
        self.assertTrue((w >= 0).all())

    def test_time_to_failure_and_latent_state_are_prequential(self):
        features = np.column_stack([self.x, self.bp])
        ttf, meta = _time_to_failure_predictor(features, self.bp, self.y, horizons=(10, 20, 30))
        self.assertEqual(ttf.shape, (self.n, 3, 3))
        self.assertEqual(meta["status"], "EVALUATED")
        latent = _latent_state_proxy(self.x)
        self.assertEqual(latent["latent_state"].shape, (self.n,))
        self.assertTrue(np.isfinite(latent["latent_stress"]).all())

    def test_robustness_matrix_contains_required_scenarios(self):
        baseline = self.bp @ np.array([0.5, 0.3, 0.2])
        robust = _robustness_matrix(self.y, self.bp, baseline, baseline)
        expected = {
            "Normal", "High_Volatility", "Low_Volatility", "Regime_Shift",
            "Information_Shock", "Missing_Data", "Source_Conflict",
            "Feature_Drift", "Prediction_Shock", "Model_Failure",
        }
        self.assertEqual(set(robust["scenarios"]), expected)

    def test_full_v6_is_research_only(self):
        result = run_experiment(
            sport="synthetic",
            x_train=self.x,
            y_train=self.y,
            oof_folds=self.folds,
            names=self.names,
            baseline_weights={"m1": 0.5, "m2": 0.3, "m3": 0.2},
            event_ids=[f"e{i}" for i in range(self.n)],
            dataset_hash="synthetic-v6",
            feature_version="test-v6",
            max_oos_rows=600,
        )
        self.assertEqual(result["status"], "EVALUATED")
        self.assertFalse(result["production_changed"])
        self.assertEqual(result["promotion"], "HOLD")
        self.assertEqual(result["evaluation_mode"], "FULL_OOS")
        self.assertIn("error_correlation", result)
        self.assertIn("future_failure", result)
        self.assertIn("regime_transition", result)
        self.assertIn("retrieval", result)
        self.assertIn("conformal", result)
        self.assertIn("adaptive_compute", result)
        self.assertIn("meta_leakage_audit", result)
        self.assertIn("fallback_config", result)
        self.assertIn("delta", result)
        for metric in ("accuracy", "logloss", "brier", "ece"):
            self.assertIn(metric, result["baseline"])
            self.assertIn(metric, result["new"])
            self.assertIn(metric, result["delta"])


if __name__ == "__main__":
    unittest.main()
