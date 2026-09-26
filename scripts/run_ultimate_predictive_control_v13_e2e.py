from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.ultimate_predictive_control_v13 import run_v13_research


def main() -> None:
    rng = np.random.default_rng(713)
    n = 480
    t = np.arange(n, dtype=float)
    latent = 0.8 * np.sin(t / 13.0) + 0.5 * np.cos(t / 29.0) + rng.normal(0, 0.55, n)
    target_p = 1.0 / (1.0 + np.exp(-latent))
    y = rng.binomial(1, target_p)

    models = {
        "lr": np.clip(0.50 + 0.18 * np.tanh(latent) + rng.normal(0, 0.09, n), 0.01, 0.99),
        "tree": np.clip(0.49 + 0.23 * np.tanh(latent * 1.05) + rng.normal(0, 0.12, n), 0.01, 0.99),
        "hgb": np.clip(0.51 + 0.16 * np.tanh(latent * 0.9) + rng.normal(0, 0.08, n), 0.01, 0.99),
        "specialist": np.clip(0.50 + 0.20 * np.tanh(latent * 1.25) + 0.04 * np.sin(t / 7.0) + rng.normal(0, 0.10, n), 0.01, 0.99),
        "ensemble_alt": np.clip(0.50 + 0.14 * np.tanh(latent * 0.7) + rng.normal(0, 0.07, n), 0.01, 0.99),
    }

    q = np.clip(1.0 - 0.15 * np.abs(np.sin(t / 17.0)), 0.70, 1.0)
    artifact = Path("results/research/ultimate_v13_e2e.json")
    result = run_v13_research(
        "synthetic_e2e",
        models,
        y,
        cutoff_utc="2026-09-26T12:00:00+00:00",
        data_quality=q,
        artifact_path=str(artifact),
    )

    assert result["status"] == "EVALUATED"
    assert result["audit"]["PIT"].startswith("PASS")
    assert result["audit"]["meta_leakage"] == "PASS"
    assert result["promotion"]["production"] == "HOLD"
    assert result["states"]["dynamic_routing"] == "EXECUTED"
    assert result["states"]["prediction_policy"] == "EXECUTED"
    assert result["states"]["prediction_output"] == "EXECUTED"
    assert result["states"]["robustness"] == "EVALUATED"
    assert result["statistical_validation"]["status"] == "EVALUATED"
    assert artifact.is_file() and artifact.stat().st_size > 0

    with artifact.open(encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["audit"]["retrieval_index_is_past_only"] is True
    assert saved["audit"]["future_label_training_rows_exclude_unmatured_horizon"] is True

    report = Path("results/research/ultimate_v13_e2e_report.md")
    report.write_text(
        "\n".join([
            "# ULTIMATE FINAL v13 — E2E Research Report",
            "",
            f"- Status: **{result['status']}**",
            "- Mode: **RESEARCH_ONLY**",
            "- Production promotion: **HOLD**",
            "- PIT: **PASS (inherited from chronological OOS input)**",
            "- Meta-Leakage: **PASS**",
            f"- OOS rows: **{result['oos_rows']}**",
            "",
            "## Performance (synthetic E2E only)",
            "",
            "| Metric | Baseline | New | Δ |",
            "|---|---:|---:|---:|",
            f"| Accuracy | {result['baseline']['accuracy']:.6f} | {result['new']['accuracy']:.6f} | {result['delta']['accuracy']:+.6f} |",
            f"| LogLoss | {result['baseline']['logloss']:.6f} | {result['new']['logloss']:.6f} | {result['delta']['logloss']:+.6f} |",
            f"| Brier | {result['baseline']['brier']:.6f} | {result['new']['brier']:.6f} | {result['delta']['brier']:+.6f} |",
            f"| ECE | {result['baseline']['ece']:.6f} | {result['new']['ece']:.6f} | {result['delta']['ece']:+.6f} |",
            "",
            "## Safety / Research State",
            "",
            f"- Router latest max weight: {result['routing']['weight_concentration_latest']:.6f}",
            f"- Latest Predictability: {result['predictability']['latest']:.6f}",
            f"- Latest Failure Risk: {result['forecast_contract']['uncertainty']['future_failure_risk']:.6f}",
            f"- Latest Strategy: {result['prediction_policy']['latest_strategy']}",
            f"- Latest Output Format: {result['prediction_output']['latest_format']}",
            "- Active Information: PROXY_ONLY",
            "- Performance success: **NOT CLAIMED**",
            "",
            "## Important",
            "",
            "This report is a synthetic integration/E2E validation artifact. It is not evidence of real-sport OOS performance or production readiness.",
        ]) + "\n",
        encoding="utf-8",
    )
    assert report.is_file() and report.stat().st_size > 0

    print("[ULTIMATE V13 E2E]")
    print("STATUS=PASS")
    print(f"OOS_ROWS={result['oos_rows']}")
    print(f"BASELINE_ACCURACY={result['baseline']['accuracy']:.6f}")
    print(f"NEW_ACCURACY={result['new']['accuracy']:.6f}")
    print(f"ACCURACY_DELTA={result['delta']['accuracy']:+.6f}")
    print(f"BASELINE_LOGLOSS={result['baseline']['logloss']:.6f}")
    print(f"NEW_LOGLOSS={result['new']['logloss']:.6f}")
    print(f"LOGLOSS_DELTA={result['delta']['logloss']:+.6f}")
    print(f"BASELINE_BRIER={result['baseline']['brier']:.6f}")
    print(f"NEW_BRIER={result['new']['brier']:.6f}")
    print(f"BRIER_DELTA={result['delta']['brier']:+.6f}")
    print(f"BASELINE_ECE={result['baseline']['ece']:.6f}")
    print(f"NEW_ECE={result['new']['ece']:.6f}")
    print(f"ECE_DELTA={result['delta']['ece']:+.6f}")
    print(f"ROUTER_MAX_WEIGHT={result['routing']['weight_concentration_latest']:.6f}")
    print(f"PREDICTABILITY_LATEST={result['predictability']['latest']:.6f}")
    print(f"FAILURE_RISK_LATEST={result['forecast_contract']['uncertainty']['future_failure_risk']:.6f}")
    print(f"STRATEGY_LATEST={result['prediction_policy']['latest_strategy']}")
    print(f"FORMAT_LATEST={result['prediction_output']['latest_format']}")


if __name__ == "__main__":
    main()
