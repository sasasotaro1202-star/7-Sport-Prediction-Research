from __future__ import annotations

import unittest

import numpy as np

from src.innovative_prediction_v2 import (
    FAILURE_HORIZON,
    _block_bootstrap_delta,
    _crossfit_binary_meta,
    _disagreement_features,
    _drift_features,
    run_experiment,
)


class InnovativePredictionV2Tests(unittest.TestCase):
    def test_disagreement_feature_shape(self):
        rng = np.random.default_rng(1)
        bp = rng.uniform(0.1, 0.9, size=(120, 4))
        z = _disagreement_features(bp)
        self.assertEqual(z.shape, (120, 13))
        self.assertTrue(np.isfinite(z).all())

    def test_drift_feature_shape_and_finite_values(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(120, 8))
        bp = rng.uniform(0.1, 0.9, size=(120, 3))
        z = _drift_features(x, bp)
        self.assertEqual(z.shape, (120, 4))
        self.assertTrue(np.isfinite(z).all())

    def test_meta_crossfit_enforces_future_label_embargo(self):
        rng = np.random.default_rng(3)
        features = rng.normal(size=(360, 6))
        target = (rng.random(360) > 0.5).astype(float)
        pred, audit = _crossfit_binary_meta(features, target, horizon=FAILURE_HORIZON)
        self.assertGreater(audit["evaluation_blocks"], 0)
        self.assertGreaterEqual(audit["min_train_to_eval_gap"], FAILURE_HORIZON + 1)
        self.assertTrue(np.isfinite(pred[np.isfinite(pred)]).all())

    def test_block_bootstrap_returns_all_metrics(self):
        rng = np.random.default_rng(4)
        y = (rng.random(360) > 0.5).astype(int)
        baseline = np.clip(rng.uniform(0.2, 0.8, size=360), 0.01, 0.99)
        candidate = np.clip(0.9 * baseline + 0.05 * y, 0.01, 0.99)
        out = _block_bootstrap_delta(y, candidate, baseline)
        self.assertEqual(out["status"], "EVALUATED")
        for metric in ("accuracy", "logloss", "brier", "ece"):
            self.assertIn("ci95", out[metric])

    def test_full_v2_experiment_is_research_only_and_has_ablation_curve(self):
        rng = np.random.default_rng(5)
        x = rng.normal(size=(600, 10))
        latent = 0.7 * x[:, 0] - 0.4 * x[:, 1] + rng.normal(scale=0.7, size=600)
        y = (latent > 0).astype(int)
        p1 = np.clip(1.0 / (1.0 + np.exp(-(0.9 * latent + 0.3 * rng.normal(size=600)))), 0.02, 0.98)
        p2 = np.clip(1.0 / (1.0 + np.exp(-(0.7 * latent - 0.2 * rng.normal(size=600)))), 0.02, 0.98)
        folds = []
        for end in range(60, 560, 60):
            te = min(end + 60, len(x))
            folds.append({
                "end": end,
                "te": te,
                "preds": {"m1": p1[end:te].tolist(), "m2": p2[end:te].tolist()},
                "event_ids": [f"e{i}" for i in range(end, te)],
            })
        result = run_experiment(
            sport="synthetic",
            x_train=x,
            y_train=y,
            oof_folds=folds,
            names=["m1", "m2"],
            baseline_weights={"m1": 0.6, "m2": 0.4},
            event_ids=[f"e{i}" for i in range(len(x))],
            dataset_hash="synthetic",
            feature_version="test",
        )
        self.assertEqual(result["status"], "EVALUATED")
        self.assertFalse(result["production_changed"])
        self.assertEqual(result["promotion"], "HOLD")
        self.assertEqual(set(result["ablation"]), set("ABCDEFGHIJ"))
        self.assertEqual(set(result["selective_prediction"]["curve"]), {"100", "95", "90", "80", "70"})
        self.assertFalse(result["meta_leakage_audit"]["frozen_holdout_used"])
        self.assertTrue(result["meta_leakage_audit"]["future_labels_as_features"] is False)
        self.assertIn("self_monitor", result["future_failure_predictor"])


if __name__ == "__main__":
    unittest.main()
