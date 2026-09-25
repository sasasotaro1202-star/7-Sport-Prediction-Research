from __future__ import annotations

"""Research-only selective risk control for chronological case-risk scores.

This layer does not alter model probabilities. It learns an acceptance threshold
from strictly earlier OOS risk/error pairs and reports the realized error rate
among accepted cases. The threshold is chosen using an exact one-sided
Clopper-Pearson upper confidence bound, making the calibration conservative.

Temporal caveat: the finite-sample binomial guarantee assumes exchangeability
between calibration and deployment cases. Chronological OOS/frozen-holdout
evaluation is therefore mandatory under real distribution shift.
"""

from typing import Sequence
import math
import numpy as np

try:
    from scipy.stats import beta as _beta
except Exception:  # pragma: no cover - dependency failure must be explicit at call time
    _beta = None


EPS = 1e-12


def _safe_float(x: float) -> float:
    x = float(x)
    if not math.isfinite(x):
        raise ValueError("non-finite value")
    return x


def _cp_upper(k: int, n: int, delta: float) -> float:
    """One-sided Clopper-Pearson upper bound for Binomial(n, p)."""
    if n <= 0 or k < 0 or k > n:
        raise ValueError("invalid binomial counts")
    if not (0.0 < delta < 1.0):
        raise ValueError("delta must be in (0,1)")
    if _beta is None:
        raise RuntimeError("scipy is required for exact Clopper-Pearson calibration")
    if k == n:
        return 1.0
    if k == 0:
        return float(1.0 - delta ** (1.0 / n))
    return float(_beta.ppf(1.0 - delta, k + 1, n - k))


def fit_acceptance_threshold(
    risk_scores: Sequence[float],
    errors: Sequence[int],
    *,
    target_error: float = 0.10,
    delta: float = 0.05,
    min_coverage: float = 0.50,
) -> dict:
    """Choose the widest low-risk accepted set whose CP upper bound <= target."""
    r = np.asarray(risk_scores, dtype=float).reshape(-1)
    e = np.asarray(errors, dtype=int).reshape(-1)
    if len(r) != len(e) or len(r) < 30:
        return {"status": "INSUFFICIENT_CALIBRATION", "n": int(len(r))}
    if not np.isfinite(r).all():
        return {"status": "NONFINITE_RISK"}
    if not np.isin(e, [0, 1]).all():
        return {"status": "INVALID_ERROR_LABEL"}
    if not (0.0 < target_error < 1.0 and 0.0 < delta < 1.0):
        raise ValueError("target_error and delta must be in (0,1)")
    if not (0.0 < min_coverage <= 1.0):
        raise ValueError("min_coverage must be in (0,1]")

    order = np.argsort(r, kind="mergesort")
    sr = r[order]
    se = e[order]
    n = len(r)
    best_k = 0
    best_upper = None

    for k in range(1, n + 1):
        cov = k / n
        if cov + EPS < min_coverage:
            continue
        upper = _cp_upper(int(np.sum(se[:k])), k, delta)
        if upper <= target_error:
            best_k = k
            best_upper = upper

    if best_k == 0:
        return {
            "status": "NO_CERTIFIED_THRESHOLD",
            "n": int(n),
            "target_error": float(target_error),
            "delta": float(delta),
            "min_coverage": float(min_coverage),
        }

    threshold = float(sr[best_k - 1])
    accepted = r <= threshold + EPS
    accepted_n = int(np.sum(accepted))
    accepted_errors = int(np.sum(e[accepted]))
    empirical_error = accepted_errors / max(1, accepted_n)

    return {
        "status": "FITTED",
        "threshold": threshold,
        "target_error": float(target_error),
        "delta": float(delta),
        "min_coverage": float(min_coverage),
        "calibration_n": int(n),
        "accepted_n": accepted_n,
        "coverage": float(accepted_n / n),
        "accepted_errors": accepted_errors,
        "empirical_error": float(empirical_error),
        "cp_upper_error": float(best_upper),
    }


def apply_threshold(risk_scores: Sequence[float], threshold: float) -> np.ndarray:
    r = np.asarray(risk_scores, dtype=float).reshape(-1)
    if not np.isfinite(r).all():
        raise ValueError("non-finite risk score")
    return r <= _safe_float(threshold) + EPS


def evaluate_acceptance(y_error: Sequence[int], accepted: Sequence[bool]) -> dict:
    e = np.asarray(y_error, dtype=int).reshape(-1)
    a = np.asarray(accepted, dtype=bool).reshape(-1)
    if len(e) != len(a):
        raise ValueError("length mismatch")
    if len(e) == 0:
        return {"status": "EMPTY"}
    n_acc = int(np.sum(a))
    n_rej = int(len(e) - n_acc)
    if n_acc:
        acc_err = int(np.sum(e[a]))
        acc_rate = float(acc_err / n_acc)
    else:
        acc_err = None
        acc_rate = None
    return {
        "status": "EVALUATED",
        "rows": int(len(e)),
        "accepted": n_acc,
        "rejected": n_rej,
        "coverage": float(n_acc / len(e)),
        "accepted_error_count": acc_err,
        "accepted_error_rate": acc_rate,
        "accepted_accuracy": None if acc_rate is None else float(1.0 - acc_rate),
    }


def evaluate_chronological_blocks(
    risk_scores: Sequence[float],
    errors: Sequence[int],
    block_ends: Sequence[int],
    *,
    target_error: float = 0.10,
    delta: float = 0.05,
    min_coverage: float = 0.50,
    min_calibration_rows: int = 180,
) -> dict:
    """Walk-forward threshold calibration using only earlier blocks."""
    r = np.asarray(risk_scores, dtype=float).reshape(-1)
    e = np.asarray(errors, dtype=int).reshape(-1)
    ends = [int(x) for x in block_ends]
    if len(r) != len(e) or not ends or ends[-1] != len(r):
        return {"status": "INVALID_BLOCKS"}
    if any(x <= 0 or x > len(r) for x in ends):
        return {"status": "INVALID_BLOCKS"}
    starts = [0] + ends[:-1]

    block_results = []
    for i, (start, end) in enumerate(zip(starts, ends)):
        calib_end = start
        if calib_end < min_calibration_rows:
            block_results.append({
                "block": i, "status": "SKIPPED_INSUFFICIENT_CALIBRATION",
                "n": int(end - start),
            })
            continue
        fit = fit_acceptance_threshold(
            r[:calib_end], e[:calib_end],
            target_error=target_error, delta=delta, min_coverage=min_coverage,
        )
        if fit.get("status") != "FITTED":
            block_results.append({
                "block": i, "status": fit.get("status"), "n": int(end - start),
            })
            continue
        accepted = apply_threshold(r[start:end], fit["threshold"])
        ev = evaluate_acceptance(e[start:end], accepted)
        block_results.append({
            "block": i,
            "status": "EVALUATED",
            "n": int(end - start),
            "threshold": float(fit["threshold"]),
            "calibration_n": int(calib_end),
            **ev,
        })

    evaluated = [x for x in block_results if x.get("status") == "EVALUATED"]
    return {
        "status": "EVALUATED" if evaluated else "INSUFFICIENT_CALIBRATION",
        "blocks": block_results,
        "evaluated_blocks": int(len(evaluated)),
        "target_error": float(target_error),
        "delta": float(delta),
        "min_coverage": float(min_coverage),
        "min_calibration_rows": int(min_calibration_rows),
        "policy": "research_only; chronological calibration; no frozen-holdout fitting",
    }


def evaluate_frozen_holdout(
    calibration_risk: Sequence[float],
    calibration_errors: Sequence[int],
    holdout_risk: Sequence[float],
    holdout_errors: Sequence[int],
    *,
    target_error: float = 0.10,
    delta: float = 0.05,
    min_coverage: float = 0.50,
) -> dict:
    """Fit threshold on pre-holdout OOS only; evaluate once on frozen holdout."""
    fit = fit_acceptance_threshold(
        calibration_risk, calibration_errors,
        target_error=target_error, delta=delta, min_coverage=min_coverage,
    )
    if fit.get("status") != "FITTED":
        return {"status": fit.get("status"), "calibration": fit}
    accepted = apply_threshold(holdout_risk, fit["threshold"])
    out = evaluate_acceptance(holdout_errors, accepted)
    return {
        "status": "EVALUATED",
        "calibration": fit,
        "holdout": out,
        "threshold": float(fit["threshold"]),
        "holdout_target_error": float(target_error),
        "policy": "research_only; threshold fit excludes frozen holdout",
    }
