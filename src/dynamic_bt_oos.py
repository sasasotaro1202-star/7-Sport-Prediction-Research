from __future__ import annotations

"""PIT-safe shock-adaptive dynamic Bradley-Terry research challenger.

Research-only: this module never mutates production model state. It estimates
latent participant strength sequentially from already-realized outcomes.
The update variance increases only after an out-of-sample surprise, allowing
faster adaptation after abrupt form changes while remaining stable during calm
periods.

This is a lightweight state-space approximation, not a full Bayesian sampler.
"""

from dataclasses import dataclass
from math import exp
from typing import Iterable


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def _clip_prob(p: float) -> float:
    return min(max(float(p), 1e-6), 1.0 - 1e-6)


@dataclass(frozen=True)
class BTEvent:
    """One event in chronological prediction order."""

    event_id: str
    event_time_utc: str
    side_a: str
    side_b: str
    outcome: int  # 1 => A, 0 => B


class ShockAdaptiveBT:
    """Dynamic Bradley-Terry with conservative surprise-triggered adaptation."""

    def __init__(
        self,
        *,
        scale: float = 1.0,
        base_rate: float = 0.16,
        stable_process_var: float = 0.010,
        shock_process_var: float = 0.080,
        observation_var: float = 0.25,
        shock_threshold: float = 0.22,
        shock_temperature: float = 0.08,
        shrinkage: float = 0.995,
        max_rating: float = 5.0,
    ) -> None:
        if scale <= 0 or base_rate <= 0 or stable_process_var < 0:
            raise ValueError("invalid positive model parameters")
        if shock_process_var < stable_process_var:
            raise ValueError("shock_process_var must be >= stable_process_var")
        if observation_var <= 0 or shock_temperature <= 0:
            raise ValueError("invalid variance/temperature parameters")
        if not 0 < shrinkage <= 1:
            raise ValueError("shrinkage must be in (0,1]")
        self.scale = float(scale)
        self.base_rate = float(base_rate)
        self.stable_process_var = float(stable_process_var)
        self.shock_process_var = float(shock_process_var)
        self.observation_var = float(observation_var)
        self.shock_threshold = float(shock_threshold)
        self.shock_temperature = float(shock_temperature)
        self.shrinkage = float(shrinkage)
        self.max_rating = float(max_rating)
        self._rating: dict[str, float] = {}
        self._variance: dict[str, float] = {}

    def _ensure(self, name: str) -> None:
        self._rating.setdefault(name, 0.0)
        self._variance.setdefault(name, 1.0)

    def predict_event(self, side_a: str, side_b: str) -> float:
        if not side_a or not side_b or side_a == side_b:
            raise ValueError("distinct non-empty participant IDs required")
        self._ensure(side_a)
        self._ensure(side_b)
        diff = (self._rating[side_a] - self._rating[side_b]) / self.scale
        return _clip_prob(_sigmoid(diff))

    def update(self, side_a: str, side_b: str, outcome: int) -> dict[str, float]:
        if outcome not in (0, 1):
            raise ValueError("outcome must be 0 or 1")
        p = self.predict_event(side_a, side_b)
        surprise = abs(float(outcome) - p)

        # Soft spike/slab process-variance interpolation. Stable events keep the
        # latent rating nearly static; large surprises unlock faster adaptation.
        shock_prob = _sigmoid(
            (surprise - self.shock_threshold) / self.shock_temperature
        )
        process_var = (
            (1.0 - shock_prob) * self.stable_process_var
            + shock_prob * self.shock_process_var
        )

        va = self._variance[side_a] + process_var
        vb = self._variance[side_b] + process_var
        ka = va / (va + self.observation_var)
        kb = vb / (vb + self.observation_var)

        residual = float(outcome) - p
        step_a = self.base_rate * ka * residual * self.scale
        step_b = self.base_rate * kb * residual * self.scale

        self._rating[side_a] = min(
            self.max_rating,
            max(-self.max_rating, self.shrinkage * self._rating[side_a] + step_a),
        )
        self._rating[side_b] = min(
            self.max_rating,
            max(-self.max_rating, self.shrinkage * self._rating[side_b] - step_b),
        )
        self._variance[side_a] = max(1e-6, (1.0 - ka) * va)
        self._variance[side_b] = max(1e-6, (1.0 - kb) * vb)

        return {
            "p_pre_update": p,
            "surprise": surprise,
            "shock_probability": shock_prob,
            "process_variance": process_var,
            "rating_a": self._rating[side_a],
            "rating_b": self._rating[side_b],
        }

    def predict_and_update(self, event: BTEvent) -> float:
        p = self.predict_event(event.side_a, event.side_b)
        self.update(event.side_a, event.side_b, event.outcome)
        return p

    def state_snapshot(self) -> dict[str, dict[str, float]]:
        names = sorted(set(self._rating) | set(self._variance))
        return {
            n: {
                "rating": float(self._rating[n]),
                "variance": float(self._variance[n]),
            }
            for n in names
        }


def chronological_predictions(events: Iterable[BTEvent]) -> list[tuple[BTEvent, float]]:
    """Predict in chronological blocks without within-block outcome leakage.

    Events sharing the exact supplied timestamp are treated as one information
    block: every prediction in the block is generated before any outcome from
    that block is consumed. This is conservative when source timestamps are
    coarser than true event times.
    """
    ordered = sorted(events, key=lambda x: (x.event_time_utc, x.event_id))
    model = ShockAdaptiveBT()
    out: list[tuple[BTEvent, float]] = []
    i = 0
    while i < len(ordered):
        ts = ordered[i].event_time_utc
        j = i
        while j < len(ordered) and ordered[j].event_time_utc == ts:
            j += 1
        block = ordered[i:j]
        predictions = [
            (event, model.predict_event(event.side_a, event.side_b))
            for event in block
        ]
        out.extend(predictions)
        for event, _ in predictions:
            model.update(event.side_a, event.side_b, event.outcome)
        i = j
    return out
