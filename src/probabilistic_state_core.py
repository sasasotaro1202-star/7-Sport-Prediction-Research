from __future__ import annotations

"""Research-only probabilistic state and scenario primitives.

This module contains no production model routing or promotion logic. Sport-specific
research lanes can compose these primitives only after identity and PIT validation.

Design principles:
- no outcome leakage at prediction time;
- explicit uncertainty propagation;
- sample-size-aware shrinkage;
- scenario mixtures instead of forced point states;
- dependence-aware variance decomposition;
- deterministic diagnostics for sensitivity and information value.
"""

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


EPS = 1e-12


def _as_float_array(values: Sequence[float], *, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ValueError(f"{name} must be non-empty")
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} must be finite")
    return arr


def effective_shrinkage_weight(
    n_effective: float,
    prior_strength: float = 20.0,
    reliability: float = 1.0,
) -> float:
    """Return a bounded empirical weight for observed evidence.

    The prior contributes prior_strength pseudo-observations. Reliability
    attenuates the effective sample size when observations are incomplete,
    conflicting, stale, or otherwise less trustworthy.

    This is a research primitive, not a calibrated production formula.
    """
    n = float(n_effective)
    ps = float(prior_strength)
    rel = float(reliability)
    if not np.isfinite(n) or n < 0.0:
        raise ValueError("n_effective must be finite and >= 0")
    if not np.isfinite(ps) or ps <= 0.0:
        raise ValueError("prior_strength must be finite and > 0")
    if not np.isfinite(rel) or not 0.0 <= rel <= 1.0:
        raise ValueError("reliability must be in [0,1]")
    effective_n = n * rel
    return float(np.clip(effective_n / (effective_n + ps), 0.0, 1.0))


def shrink_estimate(
    observed: float,
    prior: float,
    n_effective: float,
    *,
    prior_strength: float = 20.0,
    reliability: float = 1.0,
) -> dict[str, float]:
    """Combine an observed estimate with a prior using explicit shrinkage."""
    obs = float(observed)
    pr = float(prior)
    if not np.isfinite(obs) or not np.isfinite(pr):
        raise ValueError("observed and prior must be finite")
    w = effective_shrinkage_weight(n_effective, prior_strength, reliability)
    estimate = w * obs + (1.0 - w) * pr
    return {
        "observed": obs,
        "prior": pr,
        "effective_sample_size": float(n_effective),
        "reliability": float(reliability),
        "observed_weight": w,
        "prior_weight": 1.0 - w,
        "estimate": float(estimate),
        "status": "RESEARCH_ONLY",
    }


def latent_state_from_components(
    long_term: Sequence[float],
    recent: Sequence[float],
    *,
    recent_weight: float = 0.35,
    component_reliability: Sequence[float] | None = None,
) -> dict[str, object]:
    """Construct a simple component-wise latent state candidate."""
    lt = _as_float_array(long_term, name="long_term")
    rc = _as_float_array(recent, name="recent")
    if lt.shape != rc.shape:
        raise ValueError("long_term/recent shape mismatch")
    rw = float(recent_weight)
    if not np.isfinite(rw) or not 0.0 <= rw <= 1.0:
        raise ValueError("recent_weight must be in [0,1]")

    if component_reliability is None:
        rel = np.ones_like(lt)
    else:
        rel = _as_float_array(component_reliability, name="component_reliability")
        if rel.shape != lt.shape:
            raise ValueError("component_reliability shape mismatch")
        if np.any((rel < 0.0) | (rel > 1.0)):
            raise ValueError("component_reliability must be in [0,1]")

    effective_recent_weight = rw * rel
    state = lt + effective_recent_weight * (rc - lt)
    return {
        "state": state,
        "long_term": lt,
        "recent": rc,
        "recent_weight": rw,
        "effective_recent_weight_mean": float(np.mean(effective_recent_weight)),
        "recent_delta": state - lt,
        "status": "RESEARCH_ONLY",
    }


def matchup_interaction(
    side_a: Sequence[float],
    side_b: Sequence[float],
    coefficients: Sequence[float] | None = None,
) -> dict[str, object]:
    """Compute transparent pairwise matchup interaction diagnostics."""
    a = _as_float_array(side_a, name="side_a")
    b = _as_float_array(side_b, name="side_b")
    if a.shape != b.shape:
        raise ValueError("side_a/side_b shape mismatch")
    if coefficients is None:
        coef = np.ones_like(a)
    else:
        coef = _as_float_array(coefficients, name="coefficients")
        if coef.shape != a.shape:
            raise ValueError("coefficients shape mismatch")
    delta = coef * (a - b)
    synergy = coef * (a * b)
    return {
        "delta": delta,
        "absolute_delta": np.abs(delta),
        "synergy_proxy": synergy,
        "status": "RESEARCH_ONLY",
    }


def mixture_mean_variance(
    probabilities: Sequence[float],
    scenario_weights: Sequence[float],
) -> dict[str, float]:
    """Aggregate Bernoulli scenario uncertainty with total variance.

    Var(Y) = E[p_s(1-p_s)] + Var(p_s).
    """
    p = _as_float_array(probabilities, name="probabilities")
    w = _as_float_array(scenario_weights, name="scenario_weights")
    if p.shape != w.shape:
        raise ValueError("probabilities/scenario_weights shape mismatch")
    if np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("probabilities must be in [0,1]")
    if np.any(w < 0.0):
        raise ValueError("scenario_weights must be >= 0")
    total = float(np.sum(w))
    if total <= 0.0:
        raise ValueError("scenario_weights must have positive sum")
    w = w / total
    mean_p = float(np.sum(w * p))
    within = float(np.sum(w * p * (1.0 - p)))
    between = float(np.sum(w * (p - mean_p) ** 2))
    total_var = within + between
    return {
        "mean_probability": mean_p,
        "within_scenario_variance": within,
        "between_scenario_variance": between,
        "total_variance": total_var,
        "uncertainty_fraction_between_scenarios": between / max(total_var, EPS),
        "status": "RESEARCH_ONLY",
    }


def probability_sensitivity(
    baseline: float,
    perturbed: float,
    perturbation_size: float | None = None,
) -> dict[str, float]:
    """Measure probability movement under a controlled perturbation."""
    b = float(baseline)
    p = float(perturbed)
    if not np.isfinite(b) or not np.isfinite(p):
        raise ValueError("baseline/perturbed must be finite")
    if not 0.0 <= b <= 1.0 or not 0.0 <= p <= 1.0:
        raise ValueError("baseline/perturbed must be in [0,1]")
    delta = p - b
    out = {
        "baseline_probability": b,
        "perturbed_probability": p,
        "absolute_change": abs(delta),
        "direction": float(np.sign(delta)),
        "status": "RESEARCH_ONLY",
    }
    if perturbation_size is not None:
        eps = float(perturbation_size)
        if not np.isfinite(eps) or eps <= 0.0:
            raise ValueError("perturbation_size must be > 0")
        out["local_slope"] = delta / eps
    return out


def _entropy(probabilities: np.ndarray) -> float:
    p = np.asarray(probabilities, dtype=float)
    q = np.clip(p, EPS, 1.0)
    total = float(np.sum(q))
    if total <= 0.0:
        raise ValueError("probabilities must have positive sum")
    q = q / total
    return float(-np.sum(q * np.log(q)))


def expected_information_gain(
    prior_probabilities: Sequence[float],
    posterior_probabilities: Sequence[Sequence[float]],
    scenario_weights: Sequence[float],
) -> dict[str, float]:
    """Compute expected entropy reduction from an uncertain future observation.

    Information gain is a diagnostic. Query policy must additionally consider
    source reliability, latency, cost and decision utility.
    """
    prior = _as_float_array(prior_probabilities, name="prior_probabilities")
    post = np.asarray(posterior_probabilities, dtype=float)
    weights = _as_float_array(scenario_weights, name="scenario_weights")
    if post.ndim != 2 or post.shape[1] != len(prior):
        raise ValueError("posterior shape mismatch")
    if len(post) != len(weights):
        raise ValueError("posterior/scenario_weights length mismatch")
    if not np.isfinite(post).all():
        raise ValueError("posterior must be finite")
    if np.any(prior < 0.0) or np.any(post < 0.0):
        raise ValueError("probabilities must be >= 0")
    if np.sum(prior) <= 0.0 or np.any(np.sum(post, axis=1) <= 0.0):
        raise ValueError("probability vectors must have positive sum")
    if np.any(weights < 0.0) or np.sum(weights) <= 0.0:
        raise ValueError("scenario_weights must be non-negative with positive sum")
    weights = weights / np.sum(weights)

    prior_h = _entropy(prior)
    posterior_h = float(sum(w * _entropy(row) for w, row in zip(weights, post)))
    return {
        "prior_entropy": prior_h,
        "expected_posterior_entropy": posterior_h,
        "expected_information_gain": prior_h - posterior_h,
        "status": "RESEARCH_ONLY",
    }


@dataclass(frozen=True)
class ScenarioMixture:
    """Immutable event-level scenario description for research experiments."""

    scenario_id: str
    probability: float
    weight: float

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if not 0.0 <= float(self.probability) <= 1.0:
            raise ValueError("probability must be in [0,1]")
        if not np.isfinite(float(self.weight)) or float(self.weight) < 0.0:
            raise ValueError("weight must be finite and >= 0")


def normalize_scenarios(scenarios: Iterable[ScenarioMixture]) -> list[ScenarioMixture]:
    items = list(scenarios)
    if not items:
        raise ValueError("scenarios must be non-empty")
    total = sum(float(x.weight) for x in items)
    if total <= 0.0:
        raise ValueError("scenario weights must have positive sum")
    return [
        ScenarioMixture(
            x.scenario_id,
            float(x.probability),
            float(x.weight) / total,
        )
        for x in items
    ]


def cluster_effective_sample_size(
    cluster_sizes: Sequence[float],
    intracluster_correlation: float = 0.0,
) -> dict[str, float]:
    """Approximate information loss from within-event dependence."""
    sizes = _as_float_array(cluster_sizes, name="cluster_sizes")
    if np.any(sizes <= 0.0):
        raise ValueError("cluster_sizes must be > 0")
    rho = float(intracluster_correlation)
    if not np.isfinite(rho) or not 0.0 <= rho < 1.0:
        raise ValueError("intracluster_correlation must be in [0,1)")
    nominal = float(np.sum(sizes))
    mean_cluster = float(np.mean(sizes))
    design_effect = 1.0 + (mean_cluster - 1.0) * rho
    effective = nominal / max(design_effect, 1.0)
    return {
        "nominal_sample_size": nominal,
        "cluster_count": float(len(sizes)),
        "mean_cluster_size": mean_cluster,
        "intracluster_correlation": rho,
        "design_effect": design_effect,
        "effective_sample_size": effective,
        "information_retention_fraction": effective / max(nominal, EPS),
        "status": "RESEARCH_ONLY",
    }


def binary_decision_expected_utility(
    probability_side_a: float,
    *,
    utility_a_correct: float = 1.0,
    utility_b_correct: float = 1.0,
    utility_a_wrong: float = -1.0,
    utility_b_wrong: float = -1.0,
    abstain_utility: float = 0.0,
) -> dict[str, float | str]:
    """Compute expected utility for A, B, and abstention."""
    p = float(probability_side_a)
    if not np.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ValueError("probability_side_a must be in [0,1]")
    values = {
        "A": p * float(utility_a_correct) + (1.0 - p) * float(utility_a_wrong),
        "B": (1.0 - p) * float(utility_b_correct) + p * float(utility_b_wrong),
        "ABSTAIN": float(abstain_utility),
    }
    action = max(values, key=values.get)
    return {
        "expected_utility_a": float(values["A"]),
        "expected_utility_b": float(values["B"]),
        "expected_utility_abstain": float(values["ABSTAIN"]),
        "best_action": action,
        "best_expected_utility": float(values[action]),
        "status": "RESEARCH_ONLY",
    }


def information_action_value(
    baseline_probability: float,
    posterior_probabilities: Sequence[Sequence[float]],
    scenario_weights: Sequence[float],
    *,
    utility_a_correct: float = 1.0,
    utility_b_correct: float = 1.0,
    utility_a_wrong: float = -1.0,
    utility_b_wrong: float = -1.0,
    abstain_utility: float = 0.0,
    acquisition_cost: float = 0.0,
) -> dict[str, float | str]:
    """Estimate decision value of acquiring additional information.

    Posterior scenarios are possible information outcomes. The value compares
    the best current action against the expected best action after information,
    then subtracts acquisition cost.
    """
    p0 = float(baseline_probability)
    if not np.isfinite(p0) or not 0.0 <= p0 <= 1.0:
        raise ValueError("baseline_probability must be in [0,1]")
    cost = float(acquisition_cost)
    if not np.isfinite(cost) or cost < 0.0:
        raise ValueError("acquisition_cost must be finite and >= 0")
    prior = binary_decision_expected_utility(
        p0,
        utility_a_correct=utility_a_correct,
        utility_b_correct=utility_b_correct,
        utility_a_wrong=utility_a_wrong,
        utility_b_wrong=utility_b_wrong,
        abstain_utility=abstain_utility,
    )
    posterior = np.asarray(posterior_probabilities, dtype=float)
    weights = _as_float_array(scenario_weights, name="scenario_weights")
    if posterior.ndim != 2 or posterior.shape[1] != 2 or len(posterior) != len(weights):
        raise ValueError("posterior_probabilities must be [n,2] and align with weights")
    if not np.isfinite(posterior).all():
        raise ValueError("posterior_probabilities must be finite")
    if np.any((posterior < 0.0) | (posterior > 1.0)):
        raise ValueError("posterior probabilities must be in [0,1]")
    if np.any(weights < 0.0) or np.sum(weights) <= 0.0:
        raise ValueError("scenario weights must be non-negative with positive sum")
    weights = weights / np.sum(weights)
    best_values = []
    for row in posterior:
        row_eval = binary_decision_expected_utility(
            float(row[0]),
            utility_a_correct=utility_a_correct,
            utility_b_correct=utility_b_correct,
            utility_a_wrong=utility_a_wrong,
            utility_b_wrong=utility_b_wrong,
            abstain_utility=abstain_utility,
        )
        best_values.append(row_eval["best_expected_utility"])
    expected_after = float(np.sum(weights * np.asarray(best_values)))
    net_value = expected_after - prior["best_expected_utility"] - cost
    return {
        "current_best_action": str(prior["best_action"]),
        "current_best_expected_utility": float(prior["best_expected_utility"]),
        "expected_best_utility_after_information": expected_after,
        "acquisition_cost": cost,
        "net_information_value": net_value,
        "recommended_action": "ACQUIRE_MORE" if net_value > 0.0 else "PREDICT_NOW",
        "status": "RESEARCH_ONLY",
    }
