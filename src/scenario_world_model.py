from __future__ import annotations
"""Research-only future-world generator; no production routing or promotion.

Uncertainty layers:
parameter uncertainty -> latent/state uncertainty -> event randomness
-> trajectory -> outcome distribution.
"""
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
import numpy as np
from src.probabilistic_state_core import ScenarioMixture, normalize_scenarios

@dataclass(frozen=True)
class Transition:
    state: Mapping[str, Any]
    event: str | None = None

@dataclass(frozen=True)
class WorldOutcome:
    world_index: int
    scenario_id: str
    winner: str
    margin: float
    terminal_step: int
    events: tuple[str, ...]
    initial_state: Mapping[str, Any]
    terminal_state: Mapping[str, Any]

ParameterSampler = Callable[[str, np.random.Generator], Any]
InitialStateSampler = Callable[[str, Any, np.random.Generator], Mapping[str, Any]]
TransitionSampler = Callable[[Mapping[str, Any], Any, int, np.random.Generator], Transition]
TerminalPredicate = Callable[[Mapping[str, Any], int], bool]
OutcomeFunction = Callable[[Mapping[str, Any]], tuple[str, float]]

def _scenario_weights(scenarios: Sequence[ScenarioMixture]):
    normalized = normalize_scenarios(scenarios)
    weights = np.asarray([float(x.weight) for x in normalized], dtype=float)
    if not np.isfinite(weights).all() or np.any(weights < 0.0) or weights.sum() <= 0:
        raise ValueError("scenario weights must be finite, non-negative, and non-zero")
    return normalized, weights / weights.sum()

def simulate_worlds(
    scenarios: Sequence[ScenarioMixture], *,
    parameter_sampler: ParameterSampler,
    initial_state_sampler: InitialStateSampler,
    transition_sampler: TransitionSampler,
    terminal_predicate: TerminalPredicate,
    outcome_function: OutcomeFunction,
    worlds: int = 10_000,
    max_steps: int = 100,
    seed: int = 0,
) -> list[WorldOutcome]:
    """Generate deterministic-for-seed research worlds with explicit layers."""
    if int(worlds) <= 0 or int(max_steps) <= 0:
        raise ValueError("worlds and max_steps must be > 0")
    normalized, weights = _scenario_weights(scenarios)
    rng = np.random.default_rng(int(seed))
    ids = [x.scenario_id for x in normalized]
    picks = rng.choice(len(ids), size=int(worlds), p=weights)
    out: list[WorldOutcome] = []
    for idx, pick in enumerate(picks):
        sid = ids[int(pick)]
        params = parameter_sampler(sid, rng)
        state = dict(initial_state_sampler(sid, params, rng))
        initial = dict(state)
        events: list[str] = []
        terminal_step = int(max_steps)
        for step in range(1, int(max_steps) + 1):
            if terminal_predicate(state, step - 1):
                terminal_step = step - 1
                break
            transition = transition_sampler(state, params, step, rng)
            if not isinstance(transition, Transition):
                raise TypeError("transition_sampler must return Transition")
            state = dict(transition.state)
            if transition.event:
                events.append(str(transition.event))
            if terminal_predicate(state, step):
                terminal_step = step
                break
        winner, margin = outcome_function(state)
        margin = float(margin)
        if not np.isfinite(margin):
            raise ValueError("outcome margin must be finite")
        out.append(WorldOutcome(idx, sid, str(winner), margin, terminal_step,
                                tuple(events), initial, dict(state)))
    return out

def summarize_worlds(
    outcomes: Sequence[WorldOutcome], *,
    focal_winner: str = "A",
    tail_loss_margin: float = 3.0,
) -> dict[str, Any]:
    """Summarize winner, margin, scenario and tail-risk distributions."""
    if not outcomes:
        raise ValueError("outcomes must be non-empty")
    tail = float(tail_loss_margin)
    if not np.isfinite(tail) or tail < 0:
        raise ValueError("tail_loss_margin must be finite and >= 0")
    margins = np.asarray([x.margin for x in outcomes], dtype=float)
    focal = np.asarray([x.winner == focal_winner for x in outcomes], dtype=float)
    winners: dict[str, int] = {}
    scenario_counts: dict[str, int] = {}
    scenario_values: dict[str, list[float]] = {}
    for item, value in zip(outcomes, focal):
        winners[item.winner] = winners.get(item.winner, 0) + 1
        scenario_counts[item.scenario_id] = scenario_counts.get(item.scenario_id, 0) + 1
        scenario_values.setdefault(item.scenario_id, []).append(float(value))
    total = float(len(outcomes))
    scenario_dist = {k: v / total for k, v in sorted(scenario_counts.items())}
    scenario_p = {k: float(np.mean(v)) for k, v in sorted(scenario_values.items())}
    sizes = np.asarray(list(scenario_counts.values()), dtype=float)
    probs = np.asarray(list(scenario_p.values()), dtype=float)
    mean_p = float(np.mean(focal))
    weights = sizes / sizes.sum()
    between = float(np.sum(weights * (probs - mean_p) ** 2))
    lengths = [len(x.events) for x in outcomes]
    return {
        "world_count": len(outcomes),
        "focal_winner": str(focal_winner),
        "focal_win_probability": mean_p,
        "winner_distribution": {k: v / total for k, v in sorted(winners.items())},
        "margin": {
            "mean": float(np.mean(margins)), "std": float(np.std(margins)),
            "q05": float(np.quantile(margins, .05)),
            "q25": float(np.quantile(margins, .25)),
            "median": float(np.quantile(margins, .50)),
            "q75": float(np.quantile(margins, .75)),
            "q95": float(np.quantile(margins, .95)),
        },
        "tail_risk": {
            "focal_loss_margin_at_or_below": float(np.mean(margins <= -tail)),
            "focal_loss_rate": float(1.0 - mean_p),
        },
        "scenario_distribution": scenario_dist,
        "scenario_win_probability": scenario_p,
        "scenario_between_variance": between,
        "path_length": {"mean": float(np.mean(lengths)), "max": int(max(lengths))},
        "status": "RESEARCH_ONLY",
    }
