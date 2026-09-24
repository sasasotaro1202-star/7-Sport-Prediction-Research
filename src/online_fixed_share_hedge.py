from __future__ import annotations

"""Research-only causal fixed-share Hedge for probabilistic expert fusion.

Weights are updated strictly after observations are scored. Exact-timestamp
events form an atomic block so same-time outcomes cannot influence each other's
predictions.
"""

from dataclasses import dataclass
from math import exp, log
from typing import Iterable, Sequence


def _clip(p: float) -> float:
    return min(max(float(p), 1e-6), 1.0 - 1e-6)


def _normalize(values: Sequence[float]) -> list[float]:
    cleaned = [max(0.0, float(v)) if v == v else 0.0 for v in values]
    total = sum(cleaned)
    if total <= 0.0:
        return [1.0 / len(cleaned)] * len(cleaned)
    return [v / total for v in cleaned]


@dataclass(frozen=True)
class HedgeEvent:
    event_id: str
    event_time_utc: str
    outcome: int
    expert_probabilities: tuple[float, ...]


class FixedShareHedge:
    """Causal log-loss expert aggregation with conservative fixed-share reset."""

    def __init__(
        self,
        n_experts: int,
        *,
        learning_rate: float = 0.12,
        share: float = 0.05,
        baseline_weights: Sequence[float] | None = None,
        min_weight: float = 1e-4,
    ) -> None:
        if n_experts < 2:
            raise ValueError("at least two experts are required")
        if learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        if not 0.0 <= share <= 1.0:
            raise ValueError("share must be in [0,1]")
        if min_weight < 0:
            raise ValueError("min_weight must be non-negative")
        base = list(baseline_weights) if baseline_weights is not None else [1.0] * n_experts
        if len(base) != n_experts:
            raise ValueError("baseline weight length mismatch")
        self.n_experts = n_experts
        self.learning_rate = float(learning_rate)
        self.share = float(share)
        self.base = _normalize(base)
        self.min_weight = float(min_weight)
        self.weights = list(self.base)

    def predict(self, probabilities: Sequence[float]) -> float:
        if len(probabilities) != self.n_experts:
            raise ValueError("expert probability length mismatch")
        return _clip(sum(w * _clip(x) for w, x in zip(self.weights, probabilities)))

    def update(self, probabilities: Sequence[float], outcome: int) -> dict[str, object]:
        if outcome not in (0, 1):
            raise ValueError("outcome must be binary")
        probs = [_clip(x) for x in probabilities]
        losses = [
            -(float(outcome) * log(p) + (1.0 - float(outcome)) * log(1.0 - p))
            for p in probs
        ]
        before = list(self.weights)
        scores = [
            max(self.min_weight, w) * exp(-self.learning_rate * min(loss, 20.0))
            for w, loss in zip(self.weights, losses)
        ]
        q = _normalize(scores)
        self.weights = _normalize(
            [(1.0 - self.share) * w + self.share * b for w, b in zip(q, self.base)]
        )
        return {
            "expert_losses": losses,
            "weight_before": before,
            "weight_after": list(self.weights),
        }

    def state(self) -> list[float]:
        return list(self.weights)


def chronological_predictions(events: Iterable[HedgeEvent]) -> list[tuple[HedgeEvent, float]]:
    """Predict chronologically, updating only after each complete timestamp block."""
    ordered = sorted(events, key=lambda x: (x.event_time_utc, x.event_id))
    if not ordered:
        return []
    model = FixedShareHedge(len(ordered[0].expert_probabilities))
    out: list[tuple[HedgeEvent, float]] = []
    i = 0
    while i < len(ordered):
        ts = ordered[i].event_time_utc
        j = i
        while j < len(ordered) and ordered[j].event_time_utc == ts:
            j += 1
        block = ordered[i:j]
        preds = [(event, model.predict(event.expert_probabilities)) for event in block]
        out.extend(preds)
        for event, _ in preds:
            model.update(event.expert_probabilities, event.outcome)
        i = j
    return out
