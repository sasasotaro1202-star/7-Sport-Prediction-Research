from __future__ import annotations

"""Research-only temporal conformal prediction with explicit outcome maturity gates.

A calibration row is eligible for target case i only when:
1) its prediction time is strictly earlier than i's prediction time, and
2) its outcome was confirmed at or before i's prediction time.

No production probability or route is changed by this module.
"""

from datetime import datetime
from typing import Any, Iterable, Sequence

import numpy as np


EPS = 1e-12


def _times(values: Iterable[Any], name: str) -> list[datetime]:
    out: list[datetime] = []
    for value in values:
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            raise ValueError(f"{name} must contain timezone-aware timestamps")
        out.append(dt)
    if not out:
        raise ValueError(f"{name} must not be empty")
    return out


def validate_maturity(prediction_times: Sequence[Any], outcome_confirmed_at: Sequence[Any]) -> dict[str, Any]:
    pt = _times(prediction_times, "prediction_times")
    mature = _times(outcome_confirmed_at, "outcome_confirmed_at")
    if len(pt) != len(mature):
        raise ValueError("timestamp arrays must align")
    if any(pt[i] > pt[i + 1] for i in range(len(pt) - 1)):
        raise ValueError("prediction_times must be monotonically non-decreasing")
    if any(mature[i] < pt[i] for i in range(len(pt))):
        raise ValueError("outcome_confirmed_at cannot precede prediction_time")
    return {
        "status": "PASS",
        "rows": len(pt),
        "rule": "prior prediction_time < target prediction_time AND prior outcome_confirmed_at <= target prediction_time",
        "same_prediction_time_excluded": True,
    }


def _normalise_probabilities(probabilities: Any) -> np.ndarray:
    p = np.asarray(probabilities, dtype=float)
    if p.ndim != 2 or p.shape[1] < 2:
        raise ValueError("probabilities must be a 2-D matrix with at least two classes")
    if not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("probabilities must contain finite non-negative values")
    total = p.sum(axis=1, keepdims=True)
    if np.any(total <= EPS):
        raise ValueError("probabilities contain zero-mass rows")
    return p / total


def walk_forward_prediction_sets(
    y: Sequence[int],
    probabilities: Any,
    prediction_times: Sequence[Any],
    outcome_confirmed_at: Sequence[Any],
    *,
    alpha: float = 0.10,
    min_calibration: int = 60,
    max_calibration: int | None = 240,
    class_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    alpha = float(alpha)
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0,1)")
    if int(min_calibration) < 1:
        raise ValueError("min_calibration must be >= 1")
    if max_calibration is not None and int(max_calibration) < int(min_calibration):
        raise ValueError("max_calibration must be >= min_calibration")

    p = _normalise_probabilities(probabilities)
    yy = np.asarray(y, dtype=int)
    if yy.ndim != 1 or len(yy) != len(p) or np.any(yy < 0) or yy.max(initial=-1) >= p.shape[1]:
        raise ValueError("y is invalid or misaligned")
    pt = _times(prediction_times, "prediction_times")
    mature = _times(outcome_confirmed_at, "outcome_confirmed_at")
    validate_maturity(pt, mature)
    if len(pt) != len(p):
        raise ValueError("timestamp arrays must align with probabilities")

    names = [str(x) for x in (class_names or range(p.shape[1]))]
    if len(names) != p.shape[1] or len(set(names)) != len(names):
        raise ValueError("class_names must uniquely cover probability columns")

    nonconformity = 1.0 - p[np.arange(len(p)), yy]
    sets: list[list[str]] = []
    calibration_counts: list[int] = []
    actions: list[str] = []

    for i in range(len(p)):
        prior = [
            j for j in range(i)
            if pt[j] < pt[i] and mature[j] <= pt[i]
        ]
        if max_calibration is not None:
            prior = prior[-int(max_calibration):]
        calibration_counts.append(len(prior))

        if len(prior) < int(min_calibration):
            sets.append([])
            actions.append("ABSTAIN")
            continue

        scores = np.sort(nonconformity[np.asarray(prior, dtype=int)])
        threshold = int(np.ceil((len(scores) + 1) * (1.0 - alpha)))
        threshold = min(max(threshold, 1), len(scores))
        q = float(scores[threshold - 1])

        included = p[i] >= (1.0 - q - EPS)
        labels = [names[k] for k in np.flatnonzero(included)]
        sets.append(labels)
        actions.append("ABSTAIN" if not labels else ("SINGLE" if len(labels) == 1 else "SET"))

    return {
        "status": "RESEARCH_ONLY",
        "method": "maturity_gated_walk_forward_split_conformal",
        "alpha": alpha,
        "min_calibration": int(min_calibration),
        "max_calibration": int(max_calibration) if max_calibration is not None else None,
        "prediction_sets": sets,
        "actions": actions,
        "calibration_count": calibration_counts,
        "class_names": names,
        "maturity_gate": {
            "status": "PASS",
            "same_prediction_time_excluded": True,
            "rule": "prior prediction_time < target prediction_time AND outcome_confirmed_at <= target prediction_time",
        },
        "production_effect": "none",
    }


def prediction_set_metrics(result: dict[str, Any], y: Sequence[int]) -> dict[str, float]:
    yy = np.asarray(y, dtype=int)
    sets = result["prediction_sets"]
    counts = np.asarray(result["calibration_count"], dtype=int)
    sizes = np.asarray([len(x) for x in sets], dtype=int)
    eligible = counts >= int(result["min_calibration"])
    names = [str(x) for x in result.get("class_names", [])]
    if len(names) != len(set(names)) or not names:
        raise ValueError("result is missing class-name mapping")
    if len(yy) != len(sets):
        raise ValueError("y must align with prediction sets")
    contained = np.asarray(
        [0 <= int(label) < len(names) and names[int(label)] in ps
         for label, ps in zip(yy, sets)],
        dtype=bool,
    )
    return {
        "total_rows": float(len(yy)),
        "eligible_rows": float(eligible.sum()),
        "maturity_gated_fraction": float(eligible.mean()) if len(eligible) else float("nan"),
        "coverage_eligible": float(contained[eligible].mean()) if eligible.any() else float("nan"),
        "mean_set_size_eligible": float(sizes[eligible].mean()) if eligible.any() else float("nan"),
        "abstain_rate_total": float((sizes == 0).mean()) if len(sizes) else float("nan"),
    }
