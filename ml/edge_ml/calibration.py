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


def _pav(x: Sequence[float], y: Sequence[float]) -> tuple[list[float], list[float]]:
    """Isotonic (non-decreasing) fit by pool-adjacent-violators on points sorted
    by x. Returns knots (block mean x, block mean y)."""
    blocks: list[list[float]] = []  # [sum_x, sum_y, count]
    for xi, yi in sorted(zip(x, y, strict=True)):
        blocks.append([xi, yi, 1.0])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] >= blocks[-1][1] / blocks[-1][2]:
            sx, sy, n = blocks.pop()
            blocks[-1][0] += sx
            blocks[-1][1] += sy
            blocks[-1][2] += n
    return [b[0] / b[2] for b in blocks], [b[1] / b[2] for b in blocks]


class TopOutcomeCalibrator:
    """Recalibrates only the most likely outcome's probability with a monotone
    map g fitted on (top probability, top outcome happened); the other two keep
    their ratio and share 1 - g(p). With this structure the 1X2 log loss of the
    calibrated forecast is the binary log loss of g on "top outcome happened"
    plus a constant, so fitting g by binary log loss is the right objective.

    method "logistic": logit g(p) = a + b logit p (Platt scaling, 2 parameters).
    method "isotonic": pool-adjacent-violators, linear between block means,
    flat beyond the fitted range.
    The top outcome always stays the top outcome (g is capped where it would
    fall below the second one).
    """

    def __init__(self, method: str = "logistic", eps: float = 1e-4) -> None:
        if method not in ("logistic", "isotonic"):
            raise ValueError("method must be 'logistic' or 'isotonic'")
        self.method = method
        self.eps = eps
        self.params: tuple[float, float] = (0.0, 1.0)
        self.knots: tuple[list[float], list[float]] = ([], [])

    @property
    def name(self) -> str:
        return f"top-{self.method}"

    def fit_arrays(self, top: Sequence[float], hit: Sequence[float]) -> TopOutcomeCalibrator:
        import numpy as np
        from scipy.optimize import minimize

        p = np.clip(np.asarray(top, dtype=float), self.eps, 1 - self.eps)
        y = np.asarray(hit, dtype=float)
        if len(p) != len(y) or len(p) == 0:
            raise ValueError("need matching, non-empty data")
        if self.method == "logistic":
            z = np.log(p / (1 - p))

            def loss(ab: np.ndarray) -> float:
                q = 1 / (1 + np.exp(-(ab[0] + ab[1] * z)))
                q = np.clip(q, self.eps, 1 - self.eps)
                return float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean())

            res = minimize(loss, np.array([0.0, 1.0]), method="Nelder-Mead")
            self.params = (float(res.x[0]), float(res.x[1]))
        else:
            self.knots = _pav(p.tolist(), y.tolist())
        return self

    def fit(
        self, predictions: Sequence[Probabilities1X2], outcomes: Sequence[Outcome]
    ) -> TopOutcomeCalibrator:
        if len(predictions) != len(outcomes):
            raise ValueError("predictions and outcomes must have the same length")
        tops, hits = [], []
        for p, o in zip(predictions, outcomes, strict=True):
            k, v = _top(p.as_tuple())
            tops.append(v)
            hits.append(float(list(Outcome)[k] == o))
        return self.fit_arrays(tops, hits)

    def map_top(self, top):  # type: ignore[no-untyped-def]
        """g(p) for an array (or float) of top probabilities."""
        import numpy as np

        p = np.clip(np.asarray(top, dtype=float), self.eps, 1 - self.eps)
        if self.method == "logistic":
            a, b = self.params
            q = 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))
        else:
            xs, ys = self.knots
            q = np.interp(p, xs, ys) if xs else p
        return np.clip(q, self.eps, 1 - self.eps)

    def calibrate_matrix(self, probs):  # type: ignore[no-untyped-def]
        """Rows of (home, draw, away) -> calibrated rows (vectorised)."""
        import numpy as np

        pm = np.asarray(probs, dtype=float)
        order = np.array([0, 2, 1])  # tie-break HOME > AWAY > DRAW, as best_outcome
        k = order[np.argmax(pm[:, order], axis=1)]
        rows = np.arange(len(pm))
        top = pm[rows, k]
        q = self.map_top(top)
        second = np.max(np.where(np.eye(3, dtype=bool)[k], -1.0, pm), axis=1)
        # keep the top outcome on top: q / (1 - q) >= second / (1 - top)
        floor = second / np.maximum(1 - top + second, self.eps) + 1e-9
        q = np.maximum(q, floor)
        qm = pm * ((1 - q) / np.maximum(1 - top, self.eps))[:, None]
        qm[rows, k] = q
        return qm / qm.sum(axis=1, keepdims=True)

    def calibrate(self, probabilities: Probabilities1X2) -> Probabilities1X2:
        h, d, a = self.calibrate_matrix([probabilities.as_tuple()])[0]
        return Probabilities1X2.normalized(float(h), float(d), float(a))


def _top(p: tuple[float, float, float]) -> tuple[int, float]:
    order = (0, 2, 1)  # HOME > AWAY > DRAW on ties
    k = max(order, key=lambda i: (p[i], -order.index(i)))
    return k, p[k]
