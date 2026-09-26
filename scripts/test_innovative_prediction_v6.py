from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from src import innovative_prediction_v6 as v6


class InnovativePredictionV6Tests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(20260926)
        self.n = 360
        self.x = self.rng.normal(size=(self.n, 12))
        latent = 0.8 * self.x[:, 0] - 0.5 * self.x[:, 1] + self.rng.normal(scale=0.8, size=self.n)
        self.y = (latent > 0).astype(int)
        self.bp = np.column_stack([
            np.clip(1 / (1 + np.exp(-(0.9 * latent + self.rng.normal(scale=0.4, size=self.n)))), 0.03, 0.97),
            np.clip(1 / (1 + np.exp(-(0.7 * latent + self.rng.normal(scale=0.5, size=self.n)))), 0.03, 0.97),
            np.clip(1 / (1 + np.exp(-(0.6 * latent + self.rng.normal(scale=0.6, size=self.n)))), 0.03, 0.97),
        ])

    def test_error_correlation_returns_matrix(self):
        out = v6._error_correlation(self.bp, self.y)
        self.assertEqual(len(out["pairwise_error_correlation"]), 3)
        self.assertTrue(np.isfinite(np.asarray(out["pairwise_error_correlation"])).all())

    def test_feature_reliability_is_bounded(self):
        x = self.x.copy()
        x[::17, 2] = np.nan
        rel = v6._feature_reliability(x)
        self.assertEqual(rel.shape, (self.n,))
        self.assertTrue(np.all((rel >= 0.0) & (rel <= 1.0)))

    def test_prediction_dynamics_detects_flip_and_velocity(self):
        bp = self.bp.copy()
        bp[1, :] = 0.8
        bp[2, :] = 0.2
        out = v6._prediction_dynamics(bp)
        self.assertTrue(out["flip_count"][2] == 1.0)
        self.assertTrue(np.isfinite(out["velocity"]).all())
        self.assertTrue(np.isfinite(out["acceleration"]).all())

    def test_regime_transition_uses_pre_row_state(self):
        drift = np.zeros((self.n, 4))
        states = v6._regime_states(self.bp, drift)
        trans = v6._prequential_regime_transition(states)
        self.assertEqual(trans.shape, (self.n, 2))
        self.assertTrue(np.allclose(trans[v6.MIN_TRAIN:].sum(axis=1), 1.0))
        self.assertTrue(np.isfinite(trans).all())

    def test_retrieval_uses_only_prior_rows(self):
        out, rel = v6._historical_retrieval(self.x, self.y, self.bp.mean(axis=1), window=60, k=8)
        self.assertTrue(np.isnan(out[0]))
        self.assertTrue(np.isfinite(out[120:]).all())
        self.assertTrue(np.all((rel >= 0.0) & (rel <= 1.0)))

    def test_conformal_is_diagnostic(self):
        p = np.clip(self.bp.mean(axis=1), 0.01, 0.99)
        out = v6._conformal_prequential(self.y, p)
        self.assertEqual(out["status"], "EVALUATED")
        self.assertIn("90", out["levels"])
        self.assertIn("95", out["levels"])

    def test_full_v6_is_research_only(self):
        folds = []
        for end in range(60, 300, 40):
            te = min(end + 40, self.n)
            folds.append({
                "end": end,
                "te": te,
                "preds": {
                    "m1": self.bp[end:te, 0].tolist(),
                    "m2": self.bp[end:te, 1].tolist(),
                    "m3": self.bp[end:te, 2].tolist(),
                },
                "event_ids": [f"e{i}" for i in range(end, te)],
            })
        with tempfile.TemporaryDirectory() as td:
            old = v6.RESULTS
            v6.RESULTS = Path(td)
            try:
                result = v6.run_experiment(
                    sport="synthetic",
                    x_train=self.x,
                    y_train=self.y,
                    oof_folds=folds,
                    names=["m1", "m2", "m3"],
                    baseline_weights={"m1": 0.5, "m2": 0.3, "m3": 0.2},
                    event_ids=[f"e{i}" for i in range(self.n)],
                    dataset_hash="synthetic",
                    feature_version="test-v6",
                )
            finally:
                v6.RESULTS = old
        self.assertEqual(result["status"], "EVALUATED")
        self.assertFalse(result["production_changed"])
        self.assertEqual(result["promotion"], "HOLD")
        self.assertFalse(result["meta_leakage_audit"]["frozen_holdout_used"])
        self.assertFalse(result["meta_leakage_audit"]["random_split_used"])
        self.assertIn("FullArchitecture", result["ablation"])
        self.assertIn("error_correlation", result)
        self.assertIn("future_failure", result)
        self.assertIn("historical_error_retrieval", result)
        self.assertIn("conformal_risk_control", result)
        self.assertIn("decision_record", result)
        for k in ("Delta_Accuracy", "Delta_LogLoss", "Delta_Brier", "Delta_ECE"):
            self.assertIn(k, result["decision_record"])


if __name__ == "__main__":
    unittest.main()
