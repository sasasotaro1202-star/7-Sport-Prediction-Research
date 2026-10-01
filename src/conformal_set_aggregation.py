from __future__ import annotations

"""Research-only online conformal set aggregation.

This is a practical, empirical analogue of online conformal set aggregation:
multiple model-produced prediction sets are combined by weights that are
updated only after outcomes are mature. No production route/probability is
changed and no distribution-free guarantee is claimed for these inputs.
"""

from typing import Any, Iterable, Sequence

import numpy as np


def _validate(sets: Sequence[Sequence[int]], outcomes: Sequence[int], n_models: int) -> None:
    if len(sets) != len(outcomes) * n_models:
        raise ValueError("flat set rows must equal n_models * outcome rows")


def weighted_vote_set(
    model_sets: Sequence[Sequence[Sequence[int]]],
    weights: Sequence[float],
    *,
    min_vote: float = 0.5,
) -> list[list[int]]:
    """Combine each model's set by normalized weighted inclusion vote."""
    if not model_sets:
        raise ValueError("model_sets must not be empty")
    n_models = len(model_sets)
    n_rows = len(model_sets[0])
    if any(len(s) != n_rows for s in model_sets):
        raise ValueError("model set row counts must align")
    w = np.asarray(weights, dtype=float)
    if (
        w.ndim != 1
        or len(w) != n_models
        or not np.isfinite(w).all()
        or np.any(w < 0)
        or w.sum() <= 0
    ):
        raise ValueError("weights must be finite, non-negative, and positive-mass")
    w = w / w.sum()
    if not 0.0 < float(min_vote) <= 1.0:
        raise ValueError("min_vote must be in (0,1]")

    out: list[list[int]] = []
    for i in range(n_rows):
        labels = sorted({int(x) for model in model_sets for x in model[i]})
        selected = []
        for label in labels:
            vote = float(sum(w[m] for m in range(n_models) if label in model_sets[m][i]))
            if vote + 1e-12 >= float(min_vote):
                selected.append(label)
        out.append(selected)
    return out


def online_aggregate(
    model_sets: Sequence[Sequence[Sequence[int]]],
    outcomes: Sequence[int],
    prediction_times: Sequence[Any],
    outcome_confirmed_at: Sequence[Any],
    *,
    initial_weights: Sequence[float] | None = None,
    learning_rate: float = 1.0,
    min_calibration: int = 30,
    min_vote: float = 0.5,
) -> dict[str, Any]:
    """Predict then update model weights using only mature prior cases.

    A model receives reward 1 when its prediction set contains the later-known
    outcome and 0 otherwise. At time i, only j < i with
    prediction_time[j] < prediction_time[i] and outcome_confirmed_at[j] <=
    prediction_time[i] may influence weights.
    """
    if not model_sets:
        raise ValueError("model_sets must not be empty")
    n_models = len(model_sets)
    n_rows = len(outcomes)
    if any(len(s) != n_rows for s in model_sets):
        raise ValueError("model set row counts must align")
    if len(prediction_times) != n_rows or len(outcome_confirmed_at) != n_rows:
        raise ValueError("timestamps must align")
    if not 0.0 < float(learning_rate):
        raise ValueError("learning_rate must be > 0")
    if int(min_calibration) < 0:
        raise ValueError("min_calibration must be >= 0")

    def parse_times(values: Sequence[Any], name: str):
        out = []
        for value in values:
            try:
                from datetime import datetime
                dt = value if isinstance(value, datetime) else datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid_{name}_timestamp") from exc
            if dt.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
            out.append(dt)
        return out

    pt = parse_times(prediction_times, "prediction")
    mature = parse_times(outcome_confirmed_at, "outcome")
    if any(pt[i] < pt[i - 1] for i in range(1, n_rows)):
        raise ValueError("prediction_times must be monotonically non-decreasing")
    if any(mature[i] < pt[i] for i in range(n_rows)):
        raise ValueError("outcome_confirmed_at cannot precede prediction_time")

    w = np.asarray(initial_weights if initial_weights is not None else [1.0] * n_models, dtype=float)
    if w.ndim != 1 or len(w) != n_models or not np.isfinite(w).all() or np.any(w <= 0):
        raise ValueError("initial_weights must be finite and positive")
    w = w / w.sum()

    combined: list[list[int]] = []
    weight_history: list[list[float]] = []
    calibration_counts: list[int] = []
    eligible_flags: list[bool] = []

    for i in range(n_rows):
        combined.append(
            weighted_vote_set(
                [[list(row) for row in s[i:i+1]] for s in model_sets],
                w,
                min_vote=min_vote,
            )[0]
        )
        prior = [j for j in range(i) if pt[j] < pt[i] and mature[j] <= pt[i]]
        calibration_counts.append(len(prior))
        eligible = bool(prior) and len(prior) >= int(min_calibration)
        eligible_flags.append(eligible)
        weight_history.append(w.tolist())

        # No update from the current outcome: prediction strictly precedes
        # outcome maturation, and current row can never train its own prediction.
        if not eligible:
            continue
        gains = np.zeros(n_models, dtype=float)
        for m in range(n_models):
            gains[m] = float(np.mean([int(outcomes[j]) in model_sets[m][j] for j in prior]))
        log_update = float(learning_rate) * (gains - np.max(gains))
        # Keep online expert aggregation numerically stable over long runs.
        # Clipping prevents underflow to exact zero while preserving the
        # relative ordering induced by the mature prior-case gains.
        log_update = np.clip(log_update, -50.0, 50.0)
        log_w = np.log(np.clip(w, 1e-15, 1.0)) + log_update
        log_w -= np.max(log_w)
        w = np.exp(log_w)
        w = np.clip(w, 1e-12, None)
        w_sum = float(w.sum())
        if not np.isfinite(w_sum) or w_sum <= 0:
            raise RuntimeError("weight_update_nonfinite")
        w = w / w_sum

    combined_np = np.asarray([int(y) in s for y, s in zip(outcomes, combined)], dtype=bool)
    eligible_np = np.asarray(eligible_flags, dtype=bool)
    return {
        "status": "RESEARCH_ONLY",
        "combined_sets": combined,
        "coverage_total": float(combined_np.mean()) if n_rows else float("nan"),
        "coverage_eligible": (
            float(combined_np[eligible_np].mean()) if eligible_np.any() else float("nan")
        ),
        "eligible_rows": int(eligible_np.sum()),
        "calibration_counts": calibration_counts,
        "eligible_flags": eligible_flags,
        "weight_history": weight_history,
        "final_weights": w.tolist(),
        "learning_rate": float(learning_rate),
        "min_calibration": int(min_calibration),
        "min_vote": float(min_vote),
        "maturity_gate": {
            "rule": "prior prediction_time < current prediction_time AND prior outcome_confirmed_at <= current prediction_time",
            "same_prediction_time_excluded": True,
        },
        "production_effect": "none",
        "coverage_guarantee_claimed": False,
    }


def block_coverage_metrics(
    prediction_sets: Sequence[Sequence[int]],
    outcomes: Sequence[int],
    *,
    blocks: int = 4,
) -> dict[str, Any]:
    """Chronological coverage diagnostics; descriptive, not a guarantee."""
    if len(prediction_sets) != len(outcomes):
        raise ValueError("prediction_sets and outcomes must align")
    if int(blocks) < 1:
        raise ValueError("blocks must be >= 1")
    n = len(outcomes)
    if n == 0:
        return {
            "rows": 0,
            "blocks": 0,
            "overall_coverage": float("nan"),
            "block_coverages": [],
            "worst_block_coverage": float("nan"),
            "max_undercoverage": float("nan"),
        }
    actual_blocks = min(int(blocks), n)
    indices = np.array_split(np.arange(n), actual_blocks)
    block_coverages = []
    for idx in indices:
        if len(idx) == 0:
            continue
        hits = [
            int(outcomes[int(i)]) in {int(x) for x in prediction_sets[int(i)]}
            for i in idx
        ]
        block_coverages.append(float(np.mean(hits)))
    overall = float(np.mean([
        int(y) in {int(x) for x in ps}
        for ps, y in zip(prediction_sets, outcomes)
    ]))
    worst = min(block_coverages) if block_coverages else float("nan")
    return {
        "rows": int(n),
        "blocks": int(len(block_coverages)),
        "overall_coverage": overall,
        "block_coverages": block_coverages,
        "worst_block_coverage": float(worst),
        "max_undercoverage": float(overall - worst) if block_coverages else float("nan"),
        "descriptive_only": True,
        "guarantee_claimed": False,
    }
