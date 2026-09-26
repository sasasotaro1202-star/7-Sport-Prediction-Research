from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.ultimate_predictive_control_v13 import run_v13_research_from_oof


def main() -> None:
    rng = np.random.default_rng(20260926)
    n = 240
    latent = rng.normal(0.0, 1.0, n)
    y = rng.binomial(1, 1.0 / (1.0 + np.exp(-0.8 * latent)))
    oof = {
        "lr": np.clip(0.50 + 0.18 * np.tanh(latent) + rng.normal(0, 0.08, n), 0.01, 0.99),
        "tree": np.clip(0.50 + 0.23 * np.tanh(latent * 1.05) + rng.normal(0, 0.11, n), 0.01, 0.99),
        "hgb": np.clip(0.50 + 0.15 * np.tanh(latent * 0.85) + rng.normal(0, 0.07, n), 0.01, 0.99),
    }
    path = Path("results/research/test_ultimate_v13_oos_bridge.json")
    result = run_v13_research_from_oof(
        sport="synthetic_bridge",
        oof_predictions=oof,
        oof_targets=y,
        cutoff_utc="2026-09-26T13:00:00+00:00",
        artifact_path=str(path),
    )

    assert result["status"] == "EVALUATED"
    assert result["mode"] == "RESEARCH_ONLY"
    assert result["oos_rows"] == n
    assert result["audit"]["PIT"].startswith("PASS")
    assert result["audit"]["meta_leakage"] == "PASS"
    assert result["audit"]["retrieval_index_is_past_only"] is True
    assert result["promotion"]["production"] == "HOLD"
    assert result["states"]["dynamic_routing"] == "EXECUTED"
    assert result["states"]["prediction_policy"] == "EXECUTED"
    assert result["states"]["prediction_output"] == "EXECUTED"
    assert result["statistical_validation"]["status"] == "EVALUATED"
    assert path.is_file() and path.stat().st_size > 0

    # Direct adversarial causal check: changing y[i] cannot change the
    # routing weight or retrieved probability at the same prediction row.
    from src.ultimate_predictive_control_v13 import causal_router, retrieval_features

    d = np.zeros(n)
    _, w0 = causal_router(oof, y, d)
    changed = y.copy()
    changed[-1] = 1 - changed[-1]
    _, w1 = causal_router(oof, changed, d)
    for name in oof:
        assert np.isclose(w0[name][-1], w1[name][-1]), name

    X = np.column_stack([oof["lr"], oof["tree"], oof["hgb"]])
    r0 = retrieval_features(X, y)
    r1 = retrieval_features(X, changed)
    assert np.isclose(r0["probability"][-1], r1["probability"][-1])

    with path.open(encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["audit"]["router_uses_prior_outcomes_only"] is True
    print("ULTIMATE_V13_OOS_BRIDGE: PASS")
    print(f"ACCURACY_DELTA={result['delta']['accuracy']:+.6f}")
    print(f"LOGLOSS_DELTA={result['delta']['logloss']:+.6f}")
    print(f"BRIER_DELTA={result['delta']['brier']:+.6f}")
    print(f"ECE_DELTA={result['delta']['ece']:+.6f}")


if __name__ == "__main__":
    main()
