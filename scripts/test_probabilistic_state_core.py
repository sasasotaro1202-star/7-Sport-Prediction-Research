from __future__ import annotations

import unittest

import numpy as np

from src.probabilistic_state_core import (
    ScenarioMixture,
    effective_shrinkage_weight,
    expected_information_gain,
    latent_state_from_components,
    matchup_interaction,
    mixture_mean_variance,
    normalize_scenarios,
    probability_sensitivity,
    shrink_estimate,
)


class ProbabilisticStateCoreTests(unittest.TestCase):
    def test_shrinkage_weight_increases_with_effective_sample(self):
        self.assertEqual(effective_shrinkage_weight(0, prior_strength=20), 0.0)
        self.assertGreater(
            effective_shrinkage_weight(100, prior_strength=20),
            effective_shrinkage_weight(10, prior_strength=20),
        )

    def test_reliability_reduces_effective_shrinkage_weight(self):
        full = effective_shrinkage_weight(100, reliability=1.0)
        weak = effective_shrinkage_weight(100, reliability=0.2)
        self.assertLess(weak, full)

    def test_shrink_estimate_moves_toward_observation_but_not_beyond_it(self):
        out = shrink_estimate(0.90, 0.50, 10, prior_strength=20)
        self.assertGreater(out["estimate"], 0.50)
        self.assertLess(out["estimate"], 0.90)
        self.assertAlmostEqual(out["observed_weight"], 1 / 3)

    def test_latent_state_respects_component_reliability(self):
        out = latent_state_from_components(
            [80, 80, 80],
            [100, 100, 100],
            recent_weight=0.5,
            component_reliability=[1.0, 0.5, 0.0],
        )
        self.assertTrue(np.allclose(out["state"], [90, 85, 80]))

    def test_matchup_interaction_is_componentwise(self):
        out = matchup_interaction([90, 60], [70, 80], [1.0, 2.0])
        self.assertTrue(np.allclose(out["delta"], [20, -40]))
        self.assertTrue(np.allclose(out["absolute_delta"], [20, 40]))

    def test_total_variance_separates_intrinsic_and_scenario_uncertainty(self):
        out = mixture_mean_variance([0.2, 0.8], [0.5, 0.5])
        self.assertAlmostEqual(out["mean_probability"], 0.5)
        self.assertAlmostEqual(out["within_scenario_variance"], 0.16)
        self.assertAlmostEqual(out["between_scenario_variance"], 0.09)
        self.assertAlmostEqual(out["total_variance"], 0.25)

    def test_probability_sensitivity_reports_local_slope(self):
        out = probability_sensitivity(0.60, 0.54, perturbation_size=2.0)
        self.assertAlmostEqual(out["absolute_change"], 0.06)
        self.assertEqual(out["direction"], -1.0)
        self.assertAlmostEqual(out["local_slope"], -0.03)

    def test_expected_information_gain_is_positive(self):
        out = expected_information_gain(
            [0.5, 0.5],
            [[0.9, 0.1], [0.1, 0.9]],
            [0.5, 0.5],
        )
        self.assertGreater(out["expected_information_gain"], 0)

    def test_scenario_weights_are_normalized_without_mutation(self):
        original = [
            ScenarioMixture("available", 0.65, 2.0),
            ScenarioMixture("out", 0.45, 1.0),
        ]
        normalized = normalize_scenarios(original)
        self.assertAlmostEqual(normalized[0].weight, 2 / 3)
        self.assertAlmostEqual(normalized[1].weight, 1 / 3)
        self.assertEqual([x.weight for x in original], [2.0, 1.0])

    def test_invalid_probability_or_weight_fails_closed(self):
        with self.assertRaises(ValueError):
            ScenarioMixture("bad", 1.1, 1.0)
        with self.assertRaises(ValueError):
            normalize_scenarios([ScenarioMixture("a", 0.5, 0.0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
