"""Edge and expected value.

Edge = model_probability - fair_market_probability
EV   = model_probability * decimal_odds - 1   (per 1 unit staked)

A positive EV is a *model estimate*, not a guarantee. Model error and sampling
noise are large, so consumers should apply a threshold (see ``exceeds_threshold``).
"""

from __future__ import annotations

import math


def _check_probability(p: float) -> None:
    if not math.isfinite(p) or p < 0.0 or p > 1.0:
        raise ValueError(f"probability must be in [0, 1], got {p!r}")


def edge(model_probability: float, fair_market_probability: float) -> float:
    _check_probability(model_probability)
    _check_probability(fair_market_probability)
    return model_probability - fair_market_probability


def expected_value(model_probability: float, decimal_odds: float) -> float:
    _check_probability(model_probability)
    if not math.isfinite(decimal_odds) or decimal_odds <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {decimal_odds!r}")
    return model_probability * decimal_odds - 1.0


def exceeds_threshold(edge_value: float, ev_value: float, threshold: float) -> bool:
    """Conservative gate: both edge and EV must clear the threshold."""
    return edge_value >= threshold and ev_value >= threshold
