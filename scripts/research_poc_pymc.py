from __future__ import annotations

import argparse
import json
from pathlib import Path

import arviz as az
import numpy as np
import pymc as pm
from scipy.special import expit

POC_STATUS = "RESEARCH_ONLY_UNVERIFIED_PRODUCTION_EVIDENCE"

def logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-7, 1.0 - 1e-7)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log1p(-p)))

def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))

def build_synthetic_events(seed: int = 7, n_events: int = 240, n_teams: int = 12):
    rng = np.random.default_rng(seed)
    latent_strength = rng.normal(0.0, 0.8, n_teams)
    context_effect = 0.25
    team_a = np.empty(n_events, dtype=np.int64)
    team_b = np.empty(n_events, dtype=np.int64)
    context = rng.normal(0.0, 1.0, n_events)
    y = np.empty(n_events, dtype=np.int64)
    for i in range(n_events):
        a, b = rng.choice(n_teams, size=2, replace=False)
        team_a[i], team_b[i] = a, b
        latent_logit = latent_strength[a] - latent_strength[b] + context_effect * context[i]
        p = expit(latent_logit)
        y[i] = int(rng.random() < p)
    event_time = np.arange(n_events, dtype=np.int64)
    prediction_cutoff = event_time - 1
    return {
        "team_a": team_a, "team_b": team_b, "context": context, "y": y,
        "event_time": event_time, "prediction_cutoff": prediction_cutoff,
    }

def fit(seed: int = 7) -> dict:
    data = build_synthetic_events(seed=seed)
    split = int(len(data["y"]) * 0.75)
    train_a, train_b = data["team_a"][:split], data["team_b"][:split]
    train_context, train_y = data["context"][:split], data["y"][:split]
    test_a, test_b = data["team_a"][split:], data["team_b"][split:]
    test_context, test_y = data["context"][split:], data["y"][split:]
    n_teams = int(max(data["team_a"].max(), data["team_b"].max()) + 1)
    with pm.Model(coords={'team': np.arange(n_teams)}) as model:
        team_a_data = pm.Data("team_a", train_a)
        team_b_data = pm.Data("team_b", train_b)
        context_data = pm.Data("context", train_context)
        sigma_strength = pm.HalfNormal("sigma_strength", sigma=1.0)
        team_strength = pm.Normal("team_strength", mu=0.0, sigma=sigma_strength, dims="team")
        intercept = pm.Normal("intercept", mu=0.0, sigma=1.0)
        context_coef = pm.Normal("context_coef", mu=0.0, sigma=1.0)
        logit = intercept + team_strength[team_a_data] - team_strength[team_b_data] + context_coef * context_data
        p = pm.Deterministic("p", pm.math.sigmoid(logit))
        pm.Bernoulli("outcome", p=p, observed=train_y)
        idata = pm.sample(draws=400, tune=400, chains=2, cores=2, random_seed=seed, target_accept=0.9, progressbar=False, return_inferencedata=True)
    posterior = idata.posterior
    intercept_s = np.asarray(posterior["intercept"].values)
    context_s = np.asarray(posterior["context_coef"].values)
    team_s = np.asarray(posterior["team_strength"].values)
    logits = intercept_s[..., None] + context_s[..., None] * test_context[None, None, :] + team_s[..., test_a] - team_s[..., test_b]
    test_prob = np.mean(expit(logits), axis=(0, 1))
    summary = az.summary(idata, var_names=["intercept", "context_coef", "sigma_strength"], round_to=6)
    max_r_hat = float(summary["r_hat"].max())
    baseline = np.full_like(test_prob, 0.5)
    result = {
        "status": POC_STATUS, "candidate": "pymc-devs/pymc", "pymc_version": str(pm.__version__), "seed": seed,
        "data": {"n_events": int(len(data["y"])), "train_events": int(split), "test_events": int(len(test_y)), "chronological_split": True, "future_feature_leakage": False, "prediction_cutoff_before_outcome": True, "same_event_snapshot_duplication": False},
        "model": {"type": "hierarchical_team_strength_logistic", "posterior_draws": 400, "tune": 400, "chains": 2},
        "metrics": {"pymc_logloss": logloss(test_y, test_prob), "pymc_brier": brier(test_y, test_prob), "pymc_accuracy": float(np.mean((test_prob >= 0.5) == test_y)), "baseline_0_5_logloss": logloss(test_y, baseline), "baseline_0_5_brier": brier(test_y, baseline)},
        "diagnostics": {"max_r_hat": max_r_hat, "finite_probabilities": bool(np.isfinite(test_prob).all()), "posterior_samples_finite": bool(np.isfinite(team_s).all() and np.isfinite(intercept_s).all() and np.isfinite(context_s).all())},
        "evidence_boundary": {"project_sports_used": [], "production_data_used": False, "production_dependency_added": False, "performance_evidence_for_7_sport": False, "required_next_gates": ["local reproduction on project environment", "PIT-safe real-event snapshots", "chronological OOS/WFO", "calibration", "robustness", "frozen holdout", "shadow"]},
    }
    if max_r_hat > 1.05: raise RuntimeError(f'PYMC_POC_RHAT_FAIL max_r_hat={max_r_hat:.6f}')
    if not result["diagnostics"]["finite_probabilities"]: raise RuntimeError("PYMC_POC_NONFINITE_PREDICTIONS")
    return result

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("results/research/pymc_poc.json"))
    args = parser.parse_args()
    result = fit(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
