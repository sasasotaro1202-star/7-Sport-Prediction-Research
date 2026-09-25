from __future__ import annotations

import numpy as np

from src.selective_risk_control_oos import (
    apply_threshold,
    evaluate_acceptance,
    evaluate_chronological_blocks,
    evaluate_frozen_holdout,
    fit_acceptance_threshold,
)


def main() -> None:
    rng = np.random.default_rng(123)
    n = 420
    risk = np.clip(rng.beta(1.5, 4.0, n), 1e-4, 0.9999)
    errors = (rng.random(n) < (0.02 + 0.55 * risk)).astype(int)

    fit = fit_acceptance_threshold(
        risk[:300], errors[:300],
        target_error=0.18, delta=0.05, min_coverage=0.50,
    )
    assert fit["status"] == "FITTED"
    accepted = apply_threshold(risk[300:], fit["threshold"])
    evaluated = evaluate_acceptance(errors[300:], accepted)
    assert evaluated["status"] == "EVALUATED"

    walk = evaluate_chronological_blocks(
        risk, errors, [60, 120, 180, 240, 300, 360, 420],
        target_error=0.18, delta=0.05, min_coverage=0.50,
        min_calibration_rows=120,
    )
    assert walk["status"] in {"EVALUATED", "INSUFFICIENT_CALIBRATION"}

    frozen = evaluate_frozen_holdout(
        risk[:300], errors[:300], risk[300:], errors[300:],
        target_error=0.18, delta=0.05, min_coverage=0.50,
    )
    assert frozen["status"] in {"EVALUATED", "NO_CERTIFIED_THRESHOLD", "INSUFFICIENT_CALIBRATION"}

    no_cert = fit_acceptance_threshold(
        np.full(50, 0.5), np.ones(50, dtype=int),
        target_error=0.10, delta=0.05, min_coverage=0.50,
    )
    assert no_cert["status"] == "NO_CERTIFIED_THRESHOLD"

    print("SELECTIVE_RISK_CONTROL_OOS_SMOKE=PASS")


if __name__ == "__main__":
    main()
