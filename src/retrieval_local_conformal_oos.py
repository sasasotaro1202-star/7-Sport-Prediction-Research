from __future__ import annotations

"""Research-only retrieval-local temporal conformal prediction sets.

Calibration for target row i uses only prior rows whose outcomes were already
confirmed by prediction time i. Among those PIT-eligible rows, a bounded recent
pool is standardized using pool-only statistics and the nearest k cases form a
local calibration set.

This module never changes production probabilities, routes, or artifacts.
"""

from datetime import datetime
from typing import Any, Sequence

import numpy as np

EPS = 1e-12


def _parse_times(values: Sequence[Any], name: str) -> list[datetime]:
    out: list[datetime] = []
    for value in values:
        try:
            dt = (
                value
                if isinstance(value, datetime)
                else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid_{name}_timestamp") from exc
        if dt.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
        out.append(dt)
    if not out:
        raise ValueError(f"{name} must be non-empty")
    return out


def _normalise_probabilities(probabilities: Any, n: int) -> np.ndarray:
    p = np.asarray(probabilities, dtype=float)
    if p.ndim != 2 or p.shape[0] != n or p.shape[1] < 2:
        raise ValueError("probabilities must be 2-D and aligned with rows")
    if not np.isfinite(p).all() or (p < 0.0).any():
        raise ValueError("probabilities must be finite and non-negative")
    total = p.sum(axis=1, keepdims=True)
    if np.any(total <= EPS):
        raise ValueError("probabilities contain zero-mass rows")
    return p / total


def _validate_features(features: Any, n: int) -> np.ndarray:
    x = np.asarray(features, dtype=float)
    if x.ndim != 2 or x.shape[0] != n or x.shape[1] < 1:
        raise ValueError("features must be 2-D and aligned with rows")
    if not np.isfinite(x).all():
        raise ValueError("features must be finite; imputation is not implicit")
    return x


def _validate_contract(
    prediction_times: Sequence[Any],
    outcome_confirmed_at: Sequence[Any],
) -> tuple[list[datetime], list[datetime]]:
    pt = _parse_times(prediction_times, "prediction")
    mature = _parse_times(outcome_confirmed_at, "outcome")
    if len(pt) != len(mature):
        raise ValueError("prediction and maturity timestamps must align")
    if any(pt[i] < pt[i - 1] for i in range(1, len(pt))):
        raise ValueError("prediction_times must be monotonically non-decreasing")
    if any(mature[i] < pt[i] for i in range(len(pt))):
        raise ValueError("outcome_confirmed_at cannot precede prediction_time")
    return pt, mature


def _conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    if scores.ndim != 1 or len(scores) == 0:
        raise ValueError("scores must be a non-empty vector")
    rank = int(np.ceil((len(scores) + 1) * (1.0 - float(alpha))))
    rank = min(max(rank, 1), len(scores))
    return float(np.partition(scores, rank - 1)[rank - 1])


def _local_pvalues(scores: np.ndarray, row_probabilities: np.ndarray) -> np.ndarray:
    scores = np.sort(np.asarray(scores, dtype=float))
    thresholds = 1.0 - np.asarray(row_probabilities, dtype=float)
    idx = np.searchsorted(scores, thresholds, side="left")
    n = len(scores)
    return (1.0 + n - idx) / (n + 1.0)


def retrieval_local_prediction_sets(
    y: Sequence[int],
    probabilities: Any,
    features: Any,
    prediction_times: Sequence[Any],
    outcome_confirmed_at: Sequence[Any],
    *,
    alpha: float = 0.10,
    min_calibration: int = 30,
    max_pool: int = 200,
    k: int = 30,
    class_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Construct localized conformal sets with strict temporal maturity gating."""
    alpha = float(alpha)
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0,1)")
    min_cal = int(min_calibration)
    pool_cap = int(max_pool)
    k = int(k)
    if min_cal < 2 or pool_cap < min_cal or k < min_cal or k > pool_cap:
        raise ValueError("invalid calibration/pool/k configuration")

    y_arr = np.asarray(y, dtype=int).reshape(-1)
    n = len(y_arr)
    if n == 0 or np.any(y_arr < 0):
        raise ValueError("y must be non-empty and non-negative")

    p = _normalise_probabilities(probabilities, n)
    x = _validate_features(features, n)
    pt, mature = _validate_contract(prediction_times, outcome_confirmed_at)

    if int(y_arr.max(initial=-1)) >= p.shape[1]:
        raise ValueError("y contains a class outside probability columns")

    names = [str(v) for v in (class_names if class_names is not None else range(p.shape[1]))]
    if len(names) != p.shape[1] or len(set(names)) != len(names):
        raise ValueError("class_names must uniquely identify all probability columns")

    nonconformity = 1.0 - p[np.arange(n), y_arr]
    prediction_sets: list[list[str]] = []
    actions: list[str] = []
    set_sizes = np.zeros(n, dtype=int)
    pool_sizes = np.zeros(n, dtype=int)
    retrieved_sizes = np.zeros(n, dtype=int)
    nearest_distance = np.full(n, np.nan, dtype=float)
    calibration_counts = np.zeros(n, dtype=int)
    eligible = np.zeros(n, dtype=bool)
    pvalues = np.full_like(p, np.nan, dtype=float)

    for i in range(n):
        prior = np.arange(i, dtype=int)
        if len(prior):
            prior = prior[
                np.asarray(
                    [
                        pt[j] < pt[i] and mature[j] <= pt[i]
                        for j in prior
                    ],
                    dtype=bool,
                )
            ]
        if len(prior) > pool_cap:
            prior = prior[-pool_cap:]
        pool_sizes[i] = int(len(prior))

        if len(prior) < min_cal:
            prediction_sets.append([])
            actions.append("ABSTAIN")
            continue

        pool_x = x[prior]
        center = np.mean(pool_x, axis=0)
        scale = np.std(pool_x, axis=0)
        scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
        z_pool = (pool_x - center) / scale
        z_current = (x[i] - center) / scale
        distances = np.sqrt(np.mean((z_pool - z_current[None, :]) ** 2, axis=1))

        take = min(k, len(prior))
        local_idx = np.argpartition(distances, take - 1)[:take]
        local_idx = local_idx[np.argsort(distances[local_idx], kind="mergesort")]
        selected = prior[local_idx]
        retrieved_sizes[i] = int(len(selected))
        calibration_counts[i] = int(len(selected))
        nearest_distance[i] = float(distances[local_idx[0]])

        scores = np.clip(nonconformity[selected], 0.0, 1.0)
        pv = _local_pvalues(scores, p[i])
        pvalues[i] = pv
        included = pv > alpha
        labels = [names[j] for j in np.flatnonzero(included)]
        prediction_sets.append(labels)
        set_sizes[i] = int(len(labels))
        actions.append("ABSTAIN" if not labels else ("SINGLE" if len(labels) == 1 else "SET"))
        eligible[i] = True

    return {
        "status": "RESEARCH_ONLY",
        "method": "retrieval_local_temporal_conformal",
        "alpha": alpha,
        "class_names": names,
        "prediction_sets": prediction_sets,
        "actions": actions,
        "set_size": set_sizes,
        "pvalues": pvalues,
        "pool_size": pool_sizes,
        "retrieved_size": retrieved_sizes,
        "calibration_count": calibration_counts,
        "nearest_distance": nearest_distance,
        "eligible_rows": int(eligible.sum()),
        "total_rows": int(n),
        "maturity_gate": {
            "status": "PASS",
            "rule": "prior prediction_time < target prediction_time AND prior outcome_confirmed_at <= target prediction_time",
            "same_prediction_time_excluded": True,
            "current_outcome_excluded": True,
        },
        "retrieval": {
            "pool_is_recent_and_bounded": True,
            "pool_max_rows": pool_cap,
            "nearest_k": k,
            "scaling_fit_on_eligible_pool_only": True,
        },
        "production_effect": "none",
        "promotion_allowed": False,
        "coverage_guarantee_claimed": False,
    }


def retrieval_local_metrics(
    result: dict[str, Any],
    y: Sequence[int],
) -> dict[str, float]:
    yy = np.asarray(y, dtype=int).reshape(-1)
    sets = result["prediction_sets"]
    counts = np.asarray(result["calibration_count"], dtype=int)
    sizes = np.asarray(result["set_size"], dtype=int)
    minimum = int(result["retrieval"]["nearest_k"])
    # Eligible is exactly the cases whose local calibration set reached
    # min_calibration, not a warmup-inclusive global denominator.
    eligible = counts >= minimum
    if len(yy) != len(sets) or len(sizes) != len(yy):
        raise ValueError("result/y length mismatch")
    names = [str(v) for v in result["class_names"]]
    covered = np.asarray(
        [0 <= int(v) < len(names) and names[int(v)] in set(ps) for v, ps in zip(yy, sets)],
        dtype=bool,
    )
    return {
        "rows": float(len(yy)),
        "eligible_rows": float(eligible.sum()),
        "eligible_fraction": float(eligible.mean()) if len(eligible) else float("nan"),
        "coverage_eligible": float(covered[eligible].mean()) if eligible.any() else float("nan"),
        "mean_set_size_eligible": float(sizes[eligible].mean()) if eligible.any() else float("nan"),
        "singleton_rate_eligible": float((sizes[eligible] == 1).mean()) if eligible.any() else float("nan"),
        "abstain_rate_total": float((sizes == 0).mean()) if len(sizes) else float("nan"),
    }


__all__ = ["retrieval_local_prediction_sets", "retrieval_local_metrics"]
