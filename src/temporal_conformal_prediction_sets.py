from __future__ import annotations

"""Research-only temporal conformal prediction sets for binary sports outcomes.

Calibration for case i may use only strictly earlier prediction timestamps whose
outcomes were confirmed by the prediction timestamp. This is a fail-closed,
maturity-gated mechanism intended for uncertainty/set-valued output research.
It does not modify production probabilities or routes.
"""

from datetime import datetime
from typing import Any, Mapping, Sequence

import numpy as np

EPS = 1e-12


def _timestamps(values: Sequence[Any], *, name: str) -> list[datetime]:
    out: list[datetime] = []
    for value in values:
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            raise ValueError(f"{name} must contain timezone-aware timestamps")
        out.append(dt)
    if not out:
        raise ValueError(f"{name} must be non-empty")
    return out


def _probabilities(probabilities: Any) -> np.ndarray:
    p = np.asarray(probabilities, dtype=float)
    if p.ndim != 1 or len(p) == 0:
        raise ValueError("probabilities must be a non-empty 1-D array")
    if not np.isfinite(p).all() or np.any(p < 0.0) or np.any(p > 1.0):
        raise ValueError("probabilities must be finite values in [0,1]")
    return np.clip(p, EPS, 1.0 - EPS)


def _labels(y: Any, n: int) -> np.ndarray:
    arr = np.asarray(y, dtype=int)
    if arr.ndim != 1 or len(arr) != n:
        raise ValueError("y must be 1-D and aligned with probabilities")
    if np.any((arr != 0) & (arr != 1)):
        raise ValueError("binary labels must be 0 or 1")
    return arr


def validate_maturity_contract(
    prediction_times: Sequence[Any],
    outcome_confirmed_at: Sequence[Any],
) -> dict[str, Any]:
    pt = _timestamps(prediction_times, name="prediction_times")
    mature = _timestamps(outcome_confirmed_at, name="outcome_confirmed_at")
    if len(pt) != len(mature):
        raise ValueError("timestamp arrays must align")
    for i in range(1, len(pt)):
        if pt[i] < pt[i - 1]:
            raise ValueError("prediction_times must be monotonically non-decreasing")
    for i, (p_time, m_time) in enumerate(zip(pt, mature)):
        if m_time < p_time:
            raise ValueError(f"outcome_confirmed_at precedes prediction_time at row {i}")
    return {
        "status": "PASS",
        "rows": len(pt),
        "same_prediction_time_excluded": True,
    }


def _quantile_rank(scores: np.ndarray, alpha: float) -> float:
    n = len(scores)
    if n == 0:
        raise ValueError("scores must be non-empty")
    rank = int(np.ceil((n + 1.0) * (1.0 - float(alpha))))
    rank = min(max(rank, 1), n)
    return float(np.partition(scores, rank - 1)[rank - 1])


def temporal_binary_prediction_sets(
    y: Sequence[int],
    probabilities: Any,
    prediction_times: Sequence[Any],
    outcome_confirmed_at: Sequence[Any],
    *,
    alpha: float = 0.10,
    min_calibration: int = 30,
    max_calibration: int | None = 240,
    abstain_on_empty: bool = True,
) -> dict[str, Any]:
    """Construct binary conformal sets using only prior mature OOS outcomes."""
    alpha = float(alpha)
    min_calibration = int(min_calibration)
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0,1)")
    if min_calibration < 1:
        raise ValueError("min_calibration must be >= 1")
    if max_calibration is not None and int(max_calibration) < min_calibration:
        raise ValueError("max_calibration must be >= min_calibration")

    p = _probabilities(probabilities)
    y_arr = _labels(y, len(p))
    pt = _timestamps(prediction_times, name="prediction_times")
    mature = _timestamps(outcome_confirmed_at, name="outcome_confirmed_at")
    validate_maturity_contract(pt, mature)

    predicted = (p >= 0.5).astype(int)
    nonconformity = np.where(y_arr == 1, 1.0 - p, p)

    prediction_sets: list[list[int]] = []
    set_size: list[int] = []
    actions: list[str] = []
    calibration_count: list[int] = []
    calibration_cutoff: list[str | None] = []

    for i in range(len(p)):
        eligible = [
            j
            for j in range(i)
            if pt[j] < pt[i] and mature[j] <= pt[i]
        ]
        if max_calibration is not None:
            eligible = eligible[-int(max_calibration):]

        calibration_count.append(len(eligible))
        calibration_cutoff.append(
            mature[eligible[-1]].isoformat() if eligible else None
        )

        if len(eligible) < min_calibration:
            prediction_sets.append([])
            set_size.append(0)
            actions.append("ABSTAIN")
            continue

        scores = np.sort(np.asarray([nonconformity[j] for j in eligible], dtype=float))
        threshold = _quantile_rank(scores, alpha)
        included = [label for label, score in ((0, p[i]), (1, 1.0 - p[i])) if score <= threshold]
        if not included and abstain_on_empty:
            actions.append("ABSTAIN")
        else:
            actions.append("SINGLE" if len(included) == 1 else "SET")
        prediction_sets.append(included)
        set_size.append(len(included))

    eligible_mask = np.asarray(calibration_count) >= min_calibration
    return {
        "method": "temporal_binary_split_conformal",
        "alpha": alpha,
        "min_calibration": min_calibration,
        "max_calibration": max_calibration,
        "prediction_sets": prediction_sets,
        "set_size": np.asarray(set_size, dtype=int),
        "actions": actions,
        "predicted_class": predicted,
        "calibration_count": np.asarray(calibration_count, dtype=int),
        "calibration_cutoff": calibration_cutoff,
        "eligible_rows": int(eligible_mask.sum()),
        "total_rows": int(len(p)),
        "maturity_contract": {
            "status": "PASS",
            "rule": "prior prediction_time < target prediction_time AND outcome_confirmed_at <= target prediction_time",
            "same_prediction_time_excluded": True,
        },
        "production_effect": "none",
    }


def prediction_set_metrics(
    result: Mapping[str, Any],
    y: Sequence[int],
) -> dict[str, float]:
    y_arr = np.asarray(y, dtype=int)
    sets = result["prediction_sets"]
    sizes = np.asarray(result["set_size"], dtype=int)
    counts = np.asarray(result["calibration_count"], dtype=int)
    pred = np.asarray(result["predicted_class"], dtype=int)
    min_cal = int(result["min_calibration"])
    eligible = counts >= min_cal

    if len(sets) != len(y_arr):
        raise ValueError("result and y must align")

    covered = np.asarray([int(label) in set(ps) for label, ps in zip(y_arr, sets)], dtype=bool)
    singleton = sizes == 1
    singleton_eligible = eligible & singleton

    return {
        "total_rows": float(len(y_arr)),
        "eligible_rows": float(eligible.sum()),
        "eligible_fraction": float(eligible.mean()) if len(eligible) else float("nan"),
        "coverage_eligible": float(covered[eligible].mean()) if eligible.any() else float("nan"),
        "mean_set_size_eligible": float(sizes[eligible].mean()) if eligible.any() else float("nan"),
        "singleton_rate_eligible": float(singleton[eligible].mean()) if eligible.any() else float("nan"),
        "singleton_accuracy_eligible": float(
            (pred[singleton_eligible] == y_arr[singleton_eligible]).mean()
        ) if singleton_eligible.any() else float("nan"),
        "abstain_rate_total": float((sizes == 0).mean()) if len(sizes) else float("nan"),
        "abstain_rate_eligible": float((sizes[eligible] == 0).mean()) if eligible.any() else float("nan"),
        "mean_calibration_count_eligible": float(counts[eligible].mean()) if eligible.any() else float("nan"),
    }
