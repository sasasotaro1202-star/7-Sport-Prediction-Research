from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

ENGINE_VERSION = "trajectory-intelligence-v1"
EPS = 1e-9


class PITValidationError(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    if value in (None, ""):
        raise PITValidationError(f"MISSING_TIMESTAMP:{field}")
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PITValidationError(f"INVALID_TIMESTAMP:{field}") from exc
    if out.tzinfo is None:
        raise PITValidationError(f"NAIVE_TIMESTAMP:{field}")
    return out.astimezone(timezone.utc)


def _vec(value: Any, field: str) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"INVALID_VECTOR:{field}")
    arr = np.asarray(value, dtype=float).reshape(-1)
    if not np.isfinite(arr).all():
        raise ValueError(f"NONFINITE_VECTOR:{field}")
    return arr


def validate_snapshot(row: Mapping[str, Any], mode: str = "pre_event") -> dict[str, Any]:
    if mode not in {"pre_event", "in_event"}:
        raise ValueError("mode must be pre_event or in_event")
    event_id = str(row.get("event_id") or "").strip()
    if not event_id:
        raise PITValidationError("MISSING_EVENT_ID")
    event_time = _dt(row.get("event_time_utc"), "event_time_utc")
    prediction_time = _dt(row.get("prediction_time_utc"), "prediction_time_utc")
    available_at = _dt(row.get("source_available_at_utc"), "source_available_at_utc")
    if available_at > prediction_time:
        raise PITValidationError("SOURCE_AVAILABLE_AFTER_PREDICTION")
    end_time = None
    if mode == "pre_event":
        if prediction_time >= event_time:
            raise PITValidationError("PREDICTION_NOT_PRE_EVENT")
    else:
        end_time = _dt(row.get("event_end_time_utc"), "event_end_time_utc")
        if end_time <= event_time:
            raise PITValidationError("INVALID_EVENT_END")
        if not event_time <= prediction_time < end_time:
            raise PITValidationError("PREDICTION_OUTSIDE_EVENT_WINDOW")
    return {
        "event_id": event_id,
        "event_time": event_time,
        "prediction_time": prediction_time,
        "available_at": available_at,
        "event_end_time": end_time,
        "feature_vector": _vec(row.get("feature_vector"), "feature_vector"),
        "state_vector": _vec(row.get("observed_state_vector"), "observed_state_vector"),
    }


def validate_snapshots(rows: Iterable[Mapping[str, Any]], mode: str = "pre_event") -> dict[str, Any]:
    valid, errors = [], []
    for i, row in enumerate(rows):
        try:
            valid.append(validate_snapshot(row, mode))
        except Exception as exc:
            errors.append({
                "row_index": i,
                "event_id": row.get("event_id"),
                "reason": f"{type(exc).__name__}:{exc}",
            })
    return {
        "status": "PASS" if not errors else "PIT_INVALID_INPUT",
        "mode": mode,
        "input_rows": len(valid) + len(errors),
        "valid_rows": len(valid),
        "invalid_rows": len(errors),
        "events": len({r["event_id"] for r in valid}),
        "errors": errors,
        "snapshots": valid,
    }


@dataclass(frozen=True)
class TrajectoryCase:
    event_id: str
    event_time: datetime
    anchor_time: datetime
    anchor_features: np.ndarray
    horizons_seconds: tuple[int, ...]
    future_states: tuple[np.ndarray, ...]
    outcome: int


def build_trajectory_cases(
    snapshots: Sequence[dict[str, Any]],
    outcomes: Mapping[str, Mapping[str, Any]],
    horizons_seconds: Sequence[int],
) -> dict[str, Any]:
    horizons = tuple(sorted({int(h) for h in horizons_seconds if int(h) > 0}))
    if not horizons:
        raise ValueError("no positive horizons")
    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in snapshots:
        by_event.setdefault(row["event_id"], []).append(row)
    cases, skipped = [], []
    for event_id, rows in by_event.items():
        rows = sorted(rows, key=lambda x: x["prediction_time"])
        outcome = outcomes.get(event_id)
        if not isinstance(outcome, Mapping) or outcome.get("outcome_status") != "VERIFIED" or outcome.get("outcome") not in (0, 1, False, True):
            skipped.append({"event_id": event_id, "reason": "OUTCOME_NOT_VERIFIED_OR_INVALID"})
            continue
        for anchor in rows:
            future = []
            for horizon in horizons:
                target = anchor["prediction_time"].timestamp() + horizon
                match = next((r for r in rows if r["prediction_time"].timestamp() >= target), None)
                if match is None:
                    future = []
                    break
                future.append(match["state_vector"].copy())
            if len(future) != len(horizons):
                continue
            if len({len(v) for v in future}) != 1:
                skipped.append({"event_id": event_id, "reason": "STATE_DIMENSION_DRIFT"})
                continue
            cases.append(
                TrajectoryCase(
                    event_id,
                    anchor["event_time"],
                    anchor["prediction_time"],
                    anchor["feature_vector"].copy(),
                    horizons,
                    tuple(future),
                    int(bool(outcome["outcome"])),
                )
            )
    return {
        "status": "READY" if cases else "NO_COMPLETE_TRAJECTORIES",
        "cases": cases,
        "case_count": len(cases),
        "events_with_cases": len({c.event_id for c in cases}),
        "skipped": skipped,
        "horizons_seconds": list(horizons),
    }


def canonical_event_cases(cases: Sequence[TrajectoryCase], anchor_policy: str = "earliest") -> list[TrajectoryCase]:
    if anchor_policy not in {"earliest", "latest"}:
        raise ValueError("invalid anchor_policy")
    grouped: dict[str, list[TrajectoryCase]] = {}
    for case in cases:
        grouped.setdefault(case.event_id, []).append(case)
    out = []
    for rows in grouped.values():
        rows = sorted(rows, key=lambda c: c.anchor_time)
        out.append(rows[0] if anchor_policy == "earliest" else rows[-1])
    return sorted(out, key=lambda c: (c.event_time, c.event_id))


def chronological_event_folds(cases: Sequence[TrajectoryCase], n_folds: int = 6, min_train_events: int = 24) -> list[dict[str, Any]]:
    canonical = canonical_event_cases(cases)
    ids = [c.event_id for c in canonical]
    if len(ids) < min_train_events + n_folds:
        return []
    test_size = max(1, int(np.ceil((len(ids) - min_train_events) / n_folds)))
    folds = []
    end = min_train_events
    while end < len(ids) and len(folds) < n_folds:
        te = min(len(ids), end + test_size)
        if te > end:
            folds.append({
                "fold": len(folds) + 1,
                "train_event_ids": tuple(ids[:end]),
                "test_event_ids": tuple(ids[end:te]),
            })
        end = te
    return folds


def _prepare_features(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.asarray(X, dtype=float)
    missing = ~np.isfinite(X)
    med = np.nanmedian(X, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    clean = np.where(np.isfinite(X), X, med)
    scale = np.nanmedian(np.abs(clean - med), axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-6), scale, 1.0)
    return np.column_stack([(clean - med) / scale, missing.astype(float)]), med, scale


class EmpiricalTrajectoryMemory:
    """Retrieve complete historical future paths; no autoregressive self-feedback."""

    def __init__(self, k: int = 20):
        self.k = max(3, int(k))
        self.X = None
        self.cases: list[TrajectoryCase] = []
        self.med = None
        self.scale = None

    def fit(self, cases: Sequence[TrajectoryCase]) -> "EmpiricalTrajectoryMemory":
        canonical = canonical_event_cases(cases)
        if len(canonical) < 12:
            raise ValueError("insufficient_event_cases")
        base = np.vstack([c.anchor_features for c in canonical])
        self.X, self.med, self.scale = _prepare_features(base)
        self.cases = list(canonical)
        return self

    def _query(self, features: Sequence[float]) -> tuple[list[int], np.ndarray]:
        if self.X is None or self.med is None or self.scale is None:
            raise ValueError("memory_not_fit")
        x = np.asarray(features, dtype=float).reshape(1, -1)
        if x.shape[1] != len(self.med):
            raise ValueError("feature_dimension_mismatch")
        miss = ~np.isfinite(x)
        clean = np.where(np.isfinite(x), x, self.med)
        q = np.column_stack([(clean - self.med) / self.scale, miss.astype(float)])
        dist = np.sqrt(np.mean((self.X - q) ** 2, axis=1))
        k = min(self.k, len(dist))
        idx = np.argpartition(dist, k - 1)[:k]
        idx = idx[np.argsort(dist[idx])]
        d = dist[idx]
        temp = max(float(np.median(d)) + 0.25, 0.25)
        w = np.exp(-d / temp)
        w /= max(float(w.sum()), EPS)
        return idx.tolist(), w

    def predict(self, features: Sequence[float], event_id: str | None = None) -> dict[str, Any]:
        idx, weights = self._query(features)
        rows = [self.cases[i] for i in idx]
        horizons = self.cases[0].horizons_seconds
        expected, p10, p90, p_out = {}, {}, {}, {}
        for j, h in enumerate(horizons):
            mat = np.vstack([r.future_states[j] for r in rows])
            expected[str(h)] = np.average(mat, axis=0, weights=weights).tolist()
            p10[str(h)] = np.array([np.quantile(mat[:, d], 0.10) for d in range(mat.shape[1])]).tolist()
            p90[str(h)] = np.array([np.quantile(mat[:, d], 0.90) for d in range(mat.shape[1])]).tolist()
            p_out[str(h)] = float(np.average([r.outcome for r in rows], weights=weights))
        query = np.asarray(features, dtype=float).reshape(1, -1)
        missing_query = ~np.isfinite(query)
        clean_query = np.where(np.isfinite(query), query, self.med)
        q_repr = np.column_stack([(clean_query - self.med) / self.scale, missing_query.astype(float)])
        d = np.linalg.norm(self.X[idx] - np.average(self.X[idx], axis=0, weights=weights), axis=1)
        nearest = float(np.min(np.linalg.norm(self.X[idx] - q_repr[0], axis=1))) if len(idx) else None
        similarity = float(np.exp(-float(nearest) / 2.0)) if nearest is not None else 0.0
        support = float(min(1.0, np.sqrt(len(rows) / max(len(self.cases), 1))))
        return {
            "event_id": event_id,
            "status": "FORECAST_AVAILABLE",
            "engine_version": ENGINE_VERSION,
            "horizons_seconds": list(horizons),
            "expected_state": expected,
            "state_p10": p10,
            "state_p90": p90,
            "outcome_probability_by_horizon": p_out,
            "scenario_event_ids": [r.event_id for r in rows],
            "scenario_weights": [float(x) for x in weights],
            "nearest_distance": nearest,
            "predictability_score": float(np.clip(0.6 * similarity + 0.4 * support, 0.0, 1.0)),
        }


def _metrics(y: Sequence[int], p: Sequence[float]) -> dict[str, float | int]:
    yy = np.asarray(y, dtype=float)
    pp = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    ll = float(-np.mean(yy * np.log(pp) + (1 - yy) * np.log(1 - pp)))
    return {
        "logloss": ll,
        "brier": float(np.mean((pp - yy) ** 2)),
        "accuracy": float(np.mean((pp >= 0.5) == yy)),
        "n": int(len(yy)),
    }


def evaluate_oos(cases: Sequence[TrajectoryCase], n_folds: int = 6, min_train_events: int = 24, k: int = 20) -> dict[str, Any]:
    canonical = canonical_event_cases(cases)
    folds = chronological_event_folds(canonical, n_folds, min_train_events)
    if len(folds) < 3:
        return {
            "status": "INSUFFICIENT_OOS",
            "reason": "too_few_event_folds",
            "event_rows": len(canonical),
            "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        }
    by_id = {c.event_id: c for c in canonical}
    y_all, p_all, prior_all = [], [], []
    fold_improvements = []
    state_mae = {str(h): [] for h in canonical[0].horizons_seconds}
    for fold in folds:
        train = [by_id[i] for i in fold["train_event_ids"]]
        test = [by_id[i] for i in fold["test_event_ids"]]
        memory = EmpiricalTrajectoryMemory(k).fit(train)
        fp = []
        for case in test:
            pred = memory.predict(case.anchor_features, event_id=case.event_id)
            final_h = str(case.horizons_seconds[-1])
            fp.append(float(pred["outcome_probability_by_horizon"][final_h]))
            y_all.append(case.outcome)
            p_all.append(fp[-1])
            for j, h in enumerate(case.horizons_seconds):
                err = np.asarray(pred["expected_state"][str(h)]) - case.future_states[j]
                state_mae[str(h)].append(float(np.mean(np.abs(err))))
        prior = float(np.mean([c.outcome for c in train]))
        prior_all.extend([prior] * len(test))
        y_test = [by_id[i].outcome for i in fold["test_event_ids"]]
        fold_improvements.append(_metrics(y_test, [prior] * len(test))["logloss"] - _metrics(y_test, fp)["logloss"])
    traj = _metrics(y_all, p_all)
    prior = _metrics(y_all, prior_all)
    return {
        "status": "EVALUATED",
        "engine_version": ENGINE_VERSION,
        "event_rows": len(canonical),
        "folds": len(folds),
        "oos_event_rows": len(y_all),
        "trajectory_retrieval": traj,
        "prior_baseline": prior,
        "logloss_improvement_vs_prior": float(prior["logloss"] - traj["logloss"]),
        "fold_logloss_improvement_vs_prior": fold_improvements,
        "state_mae_by_horizon": {h: float(np.mean(v)) for h, v in state_mae.items() if v},
        "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        "evaluation_policy": "chronological_event_cluster; one_canonical_anchor_per_event; future_snapshots_are_labels_only",
    }


__all__ = [
    "ENGINE_VERSION","PITValidationError","TrajectoryCase","validate_snapshot",
    "validate_snapshots","build_trajectory_cases","canonical_event_cases",
    "chronological_event_folds","EmpiricalTrajectoryMemory","evaluate_oos"
]
