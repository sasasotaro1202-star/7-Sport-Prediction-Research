from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.maximum_future_generalization_v6 import run_experiment


def main() -> None:
    rng = np.random.default_rng(20260926)
    n = 900
    x = rng.normal(size=(n, 12))
    latent = 0.8 * x[:, 0] - 0.5 * x[:, 1] + 0.35 * x[:, 2] + rng.normal(scale=0.85, size=n)
    y = (latent > 0).astype(int)
    p1 = 1.0 / (1.0 + np.exp(-(0.85 * latent + rng.normal(scale=0.25, size=n))))
    p2 = 1.0 / (1.0 + np.exp(-(0.70 * latent + rng.normal(scale=0.35, size=n))))
    p3 = 1.0 / (1.0 + np.exp(-(0.55 * latent + rng.normal(scale=0.45, size=n))))
    bp = np.column_stack([p1, p2, p3]).clip(0.01, 0.99)
    names = ["lr", "et", "hgb"]
    folds = []
    for end in range(60, 840, 60):
        te = min(end + 60, n)
        folds.append({
            "end": end,
            "te": te,
            "preds": {
                names[0]: bp[end:te, 0].tolist(),
                names[1]: bp[end:te, 1].tolist(),
                names[2]: bp[end:te, 2].tolist(),
            },
            "event_ids": [f"synthetic-{i}" for i in range(end, te)],
        })

    # Synthetic PIT contract: every source observation is available strictly before prediction.
    prediction_times = np.arange(n, dtype=float)
    available_at = prediction_times - 1.0
    assert np.all(available_at < prediction_times)
    assert np.all(np.diff(prediction_times) > 0)

    report = run_experiment(
        sport="synthetic",
        x_train=x,
        y_train=y,
        oof_folds=folds,
        names=names,
        baseline_weights={"lr": 0.45, "et": 0.35, "hgb": 0.20},
        event_ids=[f"synthetic-{i}" for i in range(n)],
        dataset_hash="synthetic-v6-e2e",
        feature_version="synthetic-v6",
        max_oos_rows=780,
    )
    assert report["status"] == "EVALUATED", report
    assert report["production_changed"] is False
    assert report["promotion"] == "HOLD"
    required = {
        "error_correlation", "predictability", "future_failure",
        "regime_transition", "retrieval", "meta_label",
        "uncertainty_decomposition", "conformal", "selective_prediction",
        "robustness_matrix", "statistical_validation",
        "meta_leakage_audit", "fallback_config",
    }
    missing = sorted(required - set(report))
    if missing:
        raise RuntimeError(f"E2E_MISSING_ARTIFACT_FIELDS:{missing}")

    out = Path("results/research/maximum_future_generalization_v6/e2e")
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "REDUCED_SYNTHETIC_E2E_VERIFIED",
        "pit_audit": {
            "available_at_lt_prediction_time": True,
            "strictly_increasing_prediction_time": True,
            "future_label_as_feature": False,
        },
        "report": report,
    }
    (out / "e2e_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": payload["status"],
        "accuracy": report["new"]["accuracy"],
        "delta_accuracy": report["delta"]["accuracy"],
        "logloss": report["new"]["logloss"],
        "delta_logloss": report["delta"]["logloss"],
        "brier": report["new"]["brier"],
        "delta_brier": report["delta"]["brier"],
        "ece": report["new"]["ece"],
        "delta_ece": report["delta"]["ece"],
        "coverage": report.get("selective_prediction", {}),
        "high_confidence_accuracy": report.get("high_confidence_accuracy"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
