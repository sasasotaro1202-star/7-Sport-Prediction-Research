from __future__ import annotations

import numpy as np

from src.ultimate_predictive_control_v13 import calibrate_predictability_prior_oos


def test_calibrator_uses_development_only_and_freezes_locked_suffix():
    raw = np.linspace(0.1, 0.9, 240)
    correctness = np.array(([0, 1] * 120), dtype=int)
    calibrated_a, meta_a = calibrate_predictability_prior_oos(raw, correctness)

    altered = correctness.copy()
    altered[170:] = 1 - altered[170:]
    calibrated_b, meta_b = calibrate_predictability_prior_oos(raw, altered)

    dev_end = meta_a["dev_end"]
    assert meta_a["status"] == "FITTED_DEV_ONLY_LOGISTIC"
    assert meta_a["frozen_before_locked"] is True
    assert meta_a["locked_outcomes_update_calibrator"] is False
    assert meta_b["dev_end"] == dev_end
    assert np.allclose(calibrated_a[dev_end:], calibrated_b[dev_end:])


def test_calibrator_defers_safely_with_insufficient_development_history():
    raw = np.linspace(0.1, 0.9, 100)
    correctness = np.array(([0, 1] * 50), dtype=int)
    calibrated, meta = calibrate_predictability_prior_oos(
        raw, correctness, min_rows=120
    )
    assert meta["status"] == "FALLBACK_INSUFFICIENT_DEVELOPMENT"
    assert np.isfinite(calibrated).all()
    assert ((calibrated >= 0.01) & (calibrated <= 0.99)).all()
