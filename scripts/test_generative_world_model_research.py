from __future__ import annotations

import unittest

import numpy as np

from src.generative_world_model_research import research_one_sport, simulate_uncertainty_worlds
from src.scenario_world_model import Transition


class GenerativeWorldModelResearchTests(unittest.TestCase):
    def test_simulation_is_deterministic_and_keeps_mean_near_baseline(self):
        a = simulate_uncertainty_worlds(0.62, worlds=3000, seed=42)
        b = simulate_uncertainty_worlds(0.62, worlds=3000, seed=42)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["focal_win_probability"], 0.62, delta=0.04)
        self.assertGreaterEqual(a["margin"]["q95"], a["margin"]["q05"])

    def test_simulation_rejects_invalid_probability(self):
        with self.assertRaises(ValueError):
            simulate_uncertainty_worlds(1.01)

    def test_research_blocks_when_snapshot_file_is_empty(self):
        out = research_one_sport(
            "basketball",
            snapshots_path=__import__("pathlib").Path("/tmp/nonexistent-gwm-snapshots.jsonl"),
            outcomes_path=__import__("pathlib").Path("/tmp/nonexistent-gwm-outcomes.json"),
            min_train_events=4,
            n_folds=2,
        )
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "NO_TRAJECTORY_SNAPSHOT_ROWS")

    def test_import_contract(self):
        self.assertTrue(issubclass(Transition, object))
        self.assertTrue(np.isfinite(0.5))


if __name__ == "__main__":
    unittest.main(verbosity=2)
