"""Multi-match combination under the INDEPENDENCE APPROXIMATION.

P(all legs) = prod(P(leg)). This ignores correlation between matches, which is
acceptable for different fixtures without shared teams but is still an
approximation and must be labelled as such in every API response.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from edge_ml.value import edge, expected_value

METHOD = "independence_approximation"
MIN_LEGS = 2
MAX_LEGS = 3


@dataclass(frozen=True, slots=True)
class Leg:
    model_probability: float
    fair_market_probability: float
    decimal_odds: float


@dataclass(frozen=True, slots=True)
class CombinationResult:
    model_probability: float
    fair_market_probability: float
    combined_odds: float
    implied_probability: float  # 1 / combined_odds (includes compounded margin)
    edge: float
    expected_value: float
    method: str = METHOD


def combine(legs: Sequence[Leg]) -> CombinationResult:
    if not MIN_LEGS <= len(legs) <= MAX_LEGS:
        raise ValueError(f"a combination needs {MIN_LEGS}-{MAX_LEGS} legs, got {len(legs)}")
    model_p = math.prod(leg.model_probability for leg in legs)
    fair_p = math.prod(leg.fair_market_probability for leg in legs)
    odds = math.prod(leg.decimal_odds for leg in legs)
    return CombinationResult(
        model_probability=model_p,
        fair_market_probability=fair_p,
        combined_odds=odds,
        implied_probability=1.0 / odds,
        edge=edge(model_p, fair_p),
        expected_value=expected_value(model_p, odds),
    )
