from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.maximum_future_generalization_v6 import run_experiment


def main() -> None:
    rng = np.random.default_rng(20260926)
    n = 720
    x = rng.normal(size=(n, 10))
    latent = 0.85 * x[:, 0] - 0.50 * x[:, 1] + 0.35 * x[:, 2] + rng.normal(scale=0.85, size=n)
    y = (latent > 0).astype(int)
    bp = np.column_stack([
        1 / (1 + np.exp(-(0.90 * latent + rng.normal(scale=0.20, size=n)))),
        1 / (1 + np.exp(-(0.70 * latent + rng.normal(scale=0.30, size=n)))),
        1 / (1 + np.exp(-(0.55 * latent + rng.normal(scale=0.40, size=n)))),
    ]).clip(0.01, 0.99)
    names = ["lr", "et", "hgb"]
    folds = []
    for end in range(60, 660, 60):
        te = min(end + 60, n)
        folds.append({
            "end": end,
            "te": te,
            "preds": {names[j]: bp[end:te, j].tolist() for j in range(3)},
            "event_ids": [f"synthetic-{i}" for i in range(end, te)],
        })

    report = run_experiment(
        sport="synthetic-v13",
        x_train=x,
        y_train=y,
        oof_folds=folds,
        names=names,
        baseline_weights={"lr": 0.45, "et": 0.35, "hgb": 0.20},
        event_ids=[f"synthetic-{i}" for i in range(n)],
        dataset_hash="synthetic-v13-e2e",
        feature_version="synthetic-v13",
        max_oos_rows=660,
        feature_names=[f"f{i}" for i in range(x.shape[1])],
    )
    assert report["status"] == "EVALUATED", report
    assert report["production_changed"] is False
    assert report["promotion"] == "HOLD"
    v13 = report["v13_control"]
    assert v13["v13"]["status"] == "EVALUATED"
    assert v13["v13"]["production_changed"] is False
    assert v13["v13"]["promotion"] == "HOLD"

    required = {
        "prediction_policy", "dynamic_prediction", "prediction_output",
        "adaptive_compute", "active_information", "prediction_history",
        "future_trajectory", "prediction_lifetime", "novelty_ood",
        "error_attribution", "prediction_contract", "model_portfolio",
    }
    missing = sorted(required - set(v13))
    if missing:
        raise RuntimeError(f"V13_MISSING_REPORT_FIELDS:{missing}")

    pit_ok = all(
        row["pit_status"] == "INHERITED_STRICT_OOS_FAIL_CLOSED"
        and row["outcome_used_for_current_policy"] is False
        for row in v13["prediction_history"]["rows"]
    )
    assert pit_ok
    out = Path("results/research/maximum_future_generalization_v13/e2e")
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "REDUCED_SYNTHETIC_V13_E2E_VERIFIED",
        "metrics": {
            "accuracy": v13["prediction_ledger_summary"]["selected_metrics"]["accuracy"],
            "delta_accuracy": v13["prediction_policy"]["selected_vs_baseline"]["accuracy_delta"],
            "logloss": v13["prediction_ledger_summary"]["selected_metrics"]["logloss"],
            "delta_logloss": v13["prediction_policy"]["selected_vs_baseline"]["logloss_delta"],
            "brier": v13["prediction_ledger_summary"]["selected_metrics"]["brier"],
            "delta_brier": v13["prediction_policy"]["selected_vs_baseline"]["brier_delta"],
            "ece": v13["prediction_ledger_summary"]["selected_metrics"]["ece"],
            "delta_ece": v13["prediction_policy"]["selected_vs_baseline"]["ece_delta"],
        },
        "contracts": {
            "pit": v13["prediction_contract"]["pit_status"],
            "prediction_contract": v13["prediction_contract"]["status"],
            "active_information": v13["active_information"]["status"],
            "forecast_constraints": v13["forecast_constraints"]["status"],
        },
    }
    (out / "e2e_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
