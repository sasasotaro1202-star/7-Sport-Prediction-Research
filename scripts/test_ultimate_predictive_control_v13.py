from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.ultimate_predictive_control_v13 import (
    active_information_value_oos,
    causal_router,
    retrieval_features,
    run_v13_research,
)


def synthetic():
    rng = np.random.default_rng(20260926)
    n = 360
    latent = rng.normal(0.0, 1.0, n)
    y_prob = 1.0 / (1.0 + np.exp(-(0.8 * latent + 0.35 * np.sin(np.arange(n) / 9.0))))
    y = rng.binomial(1, y_prob)
    p1 = np.clip(0.50 + 0.22 * np.tanh(latent) + rng.normal(0, 0.10, n), 0.01, 0.99)
    p2 = np.clip(0.52 + 0.18 * np.tanh(latent * 0.8) + rng.normal(0, 0.12, n), 0.01, 0.99)
    p3 = np.clip(0.48 + 0.25 * np.tanh(latent * 1.1) + rng.normal(0, 0.11, n), 0.01, 0.99)
    p4 = np.clip(0.50 + 0.15 * np.tanh(latent * 0.6) + rng.normal(0, 0.09, n), 0.01, 0.99)
    return y, {"m1": p1, "m2": p2, "m3": p3, "m4": p4}


def main():
    y, models = synthetic()
    result_path = Path("results/research/synthetic_ultimate_v13_hardening.json")
    r = run_v13_research(
        "synthetic",
        models,
        y,
        cutoff_utc="2026-09-26T00:00:00+00:00",
        artifact_path=str(result_path),
    )
    assert r["status"] == "EVALUATED"
    assert r["mode"] == "RESEARCH_ONLY"
    assert r["audit"]["PIT"].startswith("PASS")
    assert r["audit"]["meta_leakage"] == "PASS"
    assert r["audit"]["current_outcome_in_routing_features"] is False
    assert r["audit"]["current_outcome_in_retrieval_features"] is False
    assert r["audit"]["current_outcome_in_tta_fit"] is False
    assert r["audit"]["future_failure_threshold_fit_on_training_prefix_only"] is True
    assert r["retrieval"]["pit"] == "PASS_PAST_ONLY"
    assert r["states"]["dynamic_routing"] == "EXECUTED"
    assert r["states"]["prediction_output"] == "EXECUTED"
    assert r["states"]["prediction_trajectory"] == "EXECUTED_SCENARIO_PROJECTION"
    assert r["states"]["active_information"] == "MEASURED_PROXY_OOS"
    info = r["active_information"]
    assert info["status"] == "EVALUATED"
    assert info["mode"] == "RESEARCH_ONLY_MEASURED_PROXY"
    assert info["selection_for_prediction"] is False
    assert len(info["ranked_sources"]) == len(models)
    assert info["expected_value"]["metric"] == "logloss_gain"
    assert r["promotion"]["production"] == "HOLD"
    assert result_path.is_file() and result_path.stat().st_size > 0

    # Direct causal-router adversarial test:
    # changing y[i] must not change the routing weights at row i.
    pm = models
    d = np.zeros(len(y))
    _, w0 = causal_router(pm, y, d)
    y_changed = y.copy()
    y_changed[-1] = 1 - y_changed[-1]
    _, w1 = causal_router(pm, y_changed, d)
    for name in pm:
        assert np.isclose(w0[name][-1], w1[name][-1]), name

    # Active-information ranking is an OOS research measurement only.
    info_direct = active_information_value_oos(models, y)
    assert info_direct["status"] == "EVALUATED"
    assert info_direct["selection_for_prediction"] is False

    # Retrieval itself is past-only: changing the current outcome must not
    # change the current row's retrieved probability.
    X = np.column_stack([models["m1"], models["m2"], models["m3"]])
    rr0 = retrieval_features(X, y)
    rr1 = retrieval_features(X, y_changed)
    assert np.isclose(rr0["probability"][-1], rr1["probability"][-1])

    with result_path.open(encoding="utf-8") as fh:
        loaded = json.load(fh)
    assert loaded["audit"]["router_uses_prior_outcomes_only"] is True
    print("ULTIMATE_V13_HARDENING: PASS")
    print(f"BASELINE_LOGLOSS={r['baseline']['logloss']:.6f}")
    print(f"NEW_LOGLOSS={r['new']['logloss']:.6f}")
    print(f"LOGLOSS_DELTA={r['delta']['logloss']:+.6f}")
    print(f"BASELINE_BRIER={r['baseline']['brier']:.6f}")
    print(f"NEW_BRIER={r['new']['brier']:.6f}")
    print(f"BRIER_DELTA={r['delta']['brier']:+.6f}")
    print(f"BASELINE_ECE={r['baseline']['ece']:.6f}")
    print(f"NEW_ECE={r['new']['ece']:.6f}")
    print(f"ECE_DELTA={r['delta']['ece']:+.6f}")
    print(f"ACTIVE_INFO_TOP={r['active_information']['recommended_next_source']}")
    print(f"ACTIVE_INFO_LOGLOSS_GAIN={r['active_information']['recommended_source_mean_logloss_gain']:+.6f}")


if __name__ == "__main__":
    main()
