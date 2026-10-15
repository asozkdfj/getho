"""Calibration interface.

A calibrator maps raw model probabilities to calibrated ones so that, over
many matches, "60%" predictions happen ~60% of the time. The MVP ships the
identity calibrator; a fitted calibrator (e.g. multinomial temperature /
isotonic per outcome) is planned for Phase 2 once enough paper predictions
with results exist (see docs/TODO.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from edge_ml.core import Outcome, Probabilities1X2


@runtime_checkable
class Calibrator(Protocol):
    name: str

    def fit(
        self, predictions: Sequence[Probabilities1X2], outcomes: Sequence[Outcome]
    ) -> Calibrator: ...

    def calibrate(self, probabilities: Probabilities1X2) -> Probabilities1X2: ...


class IdentityCalibrator:
    """No-op calibrator. Output == input (still guaranteed to sum to 1)."""

    name = "identity"

    def fit(
        self, predictions: Sequence[Probabilities1X2], outcomes: Sequence[Outcome]
    ) -> IdentityCalibrator:
        if len(predictions) != len(outcomes):
            raise ValueError("predictions and outcomes must have the same length")
        return self

    def calibrate(self, probabilities: Probabilities1X2) -> Probabilities1X2:
        return Probabilities1X2.normalized(*probabilities.as_tuple())


class TemperatureCalibrator:
    """Single-parameter calibration: p_k  ∝  p_k ** (1 / T).

    T > 1 softens over-confident forecasts, T < 1 sharpens timid ones. T is
    fitted by minimising log loss on held-out predictions (never on the data
    the forecasts will later be evaluated on).
    """

    name = "temperature"

    def __init__(self, temperature: float = 1.0) -> None:
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        self.temperature = temperature

    def fit(
        self, predictions: Sequence[Probabilities1X2], outcomes: Sequence[Outcome]
    ) -> TemperatureCalibrator:
        import numpy as np
        from scipy.optimize import minimize_scalar

        if len(predictions) != len(outcomes) or not predictions:
            raise ValueError("need matching, non-empty predictions and outcomes")
        p = np.array([q.as_tuple() for q in predictions])
        idx = np.array([list(Outcome).index(o) for o in outcomes])

        def loss(t: float) -> float:
            q = p ** (1.0 / t)
            q /= q.sum(axis=1, keepdims=True)
            return float(-np.log(np.clip(q[np.arange(len(idx)), idx], 1e-15, 1)).mean())

        self.temperature = float(minimize_scalar(loss, bounds=(0.5, 2.0), method="bounded").x)
        return self

    def calibrate(self, probabilities: Probabilities1X2) -> Probabilities1X2:
        h, d, a = (x ** (1.0 / self.temperature) for x in probabilities.as_tuple())
        return Probabilities1X2.normalized(h, d, a)
