from __future__ import annotations
import sys
import unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from src.probabilistic_state_core import ScenarioMixture
from src.scenario_world_model import Transition, simulate_worlds, summarize_worlds

class ScenarioWorldModelTests(unittest.TestCase):
    def specs(self):
        return [ScenarioMixture("stable",.70,.70),ScenarioMixture("volatile",.30,.30)]
    def parameter_sampler(self,sid,rng):
        return {"bias":float(rng.normal(.06 if sid=="stable" else -.03,.015))}
    def initial_state_sampler(self,sid,params,rng):
        return {"a":0,"b":0,"p":.62 if sid=="stable" else .50}
    def transition_sampler(self,state,params,step,rng):
        p=float(np.clip(state["p"]+params["bias"],.02,.98))
        if rng.random()<p:
            return Transition({"a":state["a"]+1,"b":state["b"],"p":state["p"]},"A_SCORE")
        return Transition({"a":state["a"],"b":state["b"]+1,"p":state["p"]},"B_SCORE")
    def terminal_predicate(self,state,step):
        return step>=8
    def outcome_function(self,state):
        margin=float(state["a"]-state["b"])
        return ("A" if margin>0 else "B"),margin
    def simulate(self,seed):
        return simulate_worlds(
            self.specs(),
            parameter_sampler=self.parameter_sampler,
            initial_state_sampler=self.initial_state_sampler,
            transition_sampler=self.transition_sampler,
            terminal_predicate=self.terminal_predicate,
            outcome_function=self.outcome_function,
            worlds=5_000,max_steps=8,seed=seed,
        )
    def test_fixed_seed_replays(self):
        self.assertEqual(self.simulate(42),self.simulate(42))
    def test_scenario_mix(self):
        s=summarize_worlds(self.simulate(7))
        self.assertEqual(s["world_count"],5_000)
        self.assertAlmostEqual(s["scenario_distribution"]["stable"],.70,delta=.025)
        self.assertAlmostEqual(s["scenario_distribution"]["volatile"],.30,delta=.025)
    def test_distribution_and_tail_risk(self):
        s=summarize_worlds(self.simulate(11),tail_loss_margin=3)
        self.assertGreater(s["margin"]["q95"],s["margin"]["q05"])
        self.assertTrue(0<=s["focal_win_probability"]<=1)
        self.assertTrue(0<=s["tail_risk"]["focal_loss_margin_at_or_below"]<=1)
        self.assertIn("scenario_between_variance",s)
    def test_invalid_worlds_fail_closed(self):
        with self.assertRaises(ValueError):
            simulate_worlds(
                self.specs(),
                parameter_sampler=self.parameter_sampler,
                initial_state_sampler=self.initial_state_sampler,
                transition_sampler=self.transition_sampler,
                terminal_predicate=self.terminal_predicate,
                outcome_function=self.outcome_function,
                worlds=0,
            )
    def test_invalid_transition_fails_closed(self):
        def bad(state,params,step,rng): return state
        with self.assertRaises(TypeError):
            simulate_worlds(
                self.specs(),
                parameter_sampler=self.parameter_sampler,
                initial_state_sampler=self.initial_state_sampler,
                transition_sampler=bad,
                terminal_predicate=self.terminal_predicate,
                outcome_function=self.outcome_function,
                worlds=1,max_steps=1,
            )

if __name__=="__main__":
    unittest.main(verbosity=2)
