"""Bookmaker odds -> implied probabilities -> fair (de-vigged) probabilities."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from edge_ml.core import Probabilities1X2


class DevigMethod(StrEnum):
    # Normalise 1/odds so they sum to 1. Simple, transparent, MVP default.
    PROPORTIONAL = "proportional"


def _validate_odds(odds: Sequence[float]) -> None:
    if len(odds) < 2:
        raise ValueError("need at least two outcomes")
    for o in odds:
        if not math.isfinite(o) or o <= 1.0:
            raise ValueError(f"decimal odds must be finite and > 1.0, got {o!r}")


def implied_probabilities(odds: Sequence[float]) -> list[float]:
    """Raw 1/odds. Sums to 1 + overround (the bookmaker margin)."""
    _validate_odds(odds)
    return [1.0 / o for o in odds]


def overround(odds: Sequence[float]) -> float:
    """Bookmaker margin, e.g. 0.05 for a 105% book."""
    return sum(implied_probabilities(odds)) - 1.0


def devig(odds: Sequence[float], method: DevigMethod = DevigMethod.PROPORTIONAL) -> list[float]:
    """Remove the overround and return fair probabilities summing to 1."""
    implied = implied_probabilities(odds)
    if method is DevigMethod.PROPORTIONAL:
        total = sum(implied)
        return [p / total for p in implied]
    raise ValueError(f"unsupported de-vig method: {method}")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class MarketView:
    odds_home: float
    odds_draw: float
    odds_away: float
    implied_raw: tuple[float, float, float]  # raw 1/odds, sums to 1 + overround
    fair: Probabilities1X2
    overround: float
    method: DevigMethod


def market_view_1x2(
    odds_home: float,
    odds_draw: float,
    odds_away: float,
    method: DevigMethod = DevigMethod.PROPORTIONAL,
) -> MarketView:
    odds = (odds_home, odds_draw, odds_away)
    implied = implied_probabilities(odds)
    fair = devig(odds, method)
    return MarketView(
        odds_home=odds_home,
        odds_draw=odds_draw,
        odds_away=odds_away,
        implied_raw=(implied[0], implied[1], implied[2]),
        fair=Probabilities1X2.normalized(*fair),
        overround=sum(implied) - 1.0,
        method=method,
    )
