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
