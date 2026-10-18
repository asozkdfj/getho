"""Shadow forecasts: candidates recorded next to the production model at the
same decision time and never shown (docs/experiments/shadow-forecasts-2026.md).

The candidate definitions are frozen with the protocol version: changing any
of them is a new protocol, never an edit of this one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np

from edge_ml.calibration import TopOutcomeCalibrator
from edge_ml.market import devig

PROTOCOL = "shadow-v1"
# Weight on the production model in the linear pool with the market; fixed from
# the market experiment (ADR-017: 0.25 model + 0.75 market passed its gate).
BLEND_WEIGHT = 0.25
# Frozen top-outcome map of the calibration experiment (ml/reports/
# backtest-calibration.json, frozen_map_for_confirmation); descriptive only here.
CALIBRATION_A = 0.016148045028258628
CALIBRATION_B = 1.1675089558170335

PRIMARY = ("production", "market", "blend_w0.25")

# Evaluation, fixed before any shadow-v1 row exists (see the protocol document).
EVALUATION_START = date(2026, 10, 20)  # first decision day counted (pick-day dates)
EVALUATION_END = date(2026, 12, 14)  # last decision day counted (8 weeks)
MIN_SETTLED = 1500  # fewer settled recorded fixtures -> inconclusive
MIN_GAIN = 0.002  # standard follow-up gate on log loss
CI_SEED = 20261020
DESCRIPTIVE = ("production_calibrated_v1",)


def _check(probs: Sequence[float]) -> np.ndarray:
    p = np.asarray(probs, dtype=float)
    if p.shape != (3,) or not np.all(np.isfinite(p)) or np.any(p <= 0) or abs(p.sum() - 1) > 1e-6:
        raise ValueError(f"not a 1X2 probability vector: {probs}")
    return p


def candidates(production: Sequence[float], odds: Sequence[float]) -> dict[str, list[float]]:
    """All shadow-v1 forecasts (home, draw, away) from the production
    probabilities and the decision-time 1X2 prices of the same bookmaker."""
    prod = _check(production)
    market = _check(devig(odds))
    blend = BLEND_WEIGHT * prod + (1 - BLEND_WEIGHT) * market
    cal = TopOutcomeCalibrator("logistic")
    cal.params = (CALIBRATION_A, CALIBRATION_B)
    calibrated = cal.calibrate_matrix(prod.reshape(1, 3))[0]
    return {
        "production": prod.tolist(),
        "market": market.tolist(),
        "blend_w0.25": blend.tolist(),
        "production_calibrated_v1": [float(v) for v in calibrated],
    }
