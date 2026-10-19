"""Shadow-v2: the shot-based form candidate recorded next to the production model
at the pick decision and never shown (docs/experiments/shadow-v2-2026.md).

Frozen with the protocol version; changing anything here is a new protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np

from edge_ml.core import Probabilities1X2
from edge_ml.fatigue import adjust
from edge_ml.market import devig
from edge_ml.model import ModelParams
from edge_ml.poisson import probabilities_from_expected_goals

PROTOCOL = "shadow-v2"
VARIANT = "sot_and_finishing"  # edge_ml.shots, chosen on validation (ADR-034)
# Fitted once on every season of the experiment (2019-20..2025-26, 9 leagues,
# 22,672 matches, Club Football Match Data SHA-256 ef224cf2..., production
# model 0.2.0, last kickoff 2026-05-24). Never refitted during the protocol.
OWN = (0.06111213049207317, -0.1881347759836467, -0.23421997896765948, -0.08611785139627963)
OPPONENT = (
    0.1314093571467443,
    -0.001202722151018346,
    0.06316323886944847,
    0.25743513131255347,
)
CANDIDATES = ("production", "market", "production_shots_v1")

# Evaluation, fixed before any shadow-v2 row exists (see the protocol document).
EVALUATION_START = date(2026, 11, 2)
EVALUATION_END = date(2027, 3, 28)
MIN_SETTLED = 1500
MIN_GAIN = 0.002
CI_SEED = 20261102


def shot_adjusted(
    lam_home: float,
    lam_away: float,
    x_home: Sequence[float],
    x_away: Sequence[float],
    params: ModelParams | None = None,
) -> list[float]:
    """Production expected goals moved by the frozen shot coefficients, turned
    into (home, draw, away) exactly as the production model does."""
    p = params or ModelParams()
    adj_h, adj_a = adjust(
        np.array([lam_home]),
        np.array([lam_away]),
        np.asarray([x_home], dtype=float),
        np.asarray([x_away], dtype=float),
        OWN,
        OPPONENT,
    )
    raw = probabilities_from_expected_goals(
        max(float(adj_h[0]), p.min_lambda),
        max(float(adj_a[0]), p.min_lambda),
        p.max_goals,
        p.dixon_coles_rho,
    )
    if p.draw_inflation != 1.0:
        raw = Probabilities1X2.normalized(raw.home, raw.draw * p.draw_inflation, raw.away)
    return list(raw.as_tuple())


def candidates(
    production: Sequence[float],
    odds: Sequence[float],
    expected_goals: tuple[float, float],
    x_home: Sequence[float],
    x_away: Sequence[float],
) -> dict[str, list[float]]:
    prod = np.asarray(production, dtype=float)
    if prod.shape != (3,) or abs(prod.sum() - 1) > 1e-6 or np.any(prod <= 0):
        raise ValueError(f"not a 1X2 probability vector: {production}")
    return {
        "production": prod.tolist(),
        "market": [float(v) for v in devig(odds)],
        "production_shots_v1": shot_adjusted(*expected_goals, x_home, x_away),
    }
