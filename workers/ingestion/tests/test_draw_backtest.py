from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from edge_ingestion.draw_backtest import K_MAX, apply_draw_factor, draw_factors
from edge_ingestion.feature_experiment import Row
from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch

T0 = datetime(2024, 8, 1, 14, tzinfo=UTC)


def row(i: int, draw: bool, fitted_days_before: float = 3, league: str = "x") -> Row:
    kickoff = T0 + timedelta(days=i)
    goals = (1, 1) if draw else (2, 0)
    m = BacktestMatch(MatchResult("H", "A", *goals, kickoff, season="2024-25"))
    return Row(league, m, kickoff - timedelta(days=fitted_days_before), 1.5, 1.0, (0.5, 0.25, 0.25))


def test_factor_uses_only_results_known_at_fit_time():
    rows = [row(i, draw=i % 2 == 0) for i in range(20)]  # half draws vs 25% predicted
    k = draw_factors(rows, window=4, weight=1.0)
    # rows fitted 3 days before kickoff only see matches 4+ days earlier
    assert (k[:7] == 1).all()  # fewer than 4 known results -> no change
    assert k[10] == pytest.approx(K_MAX)  # observed 2/4 vs 1.0 expected -> 2.0, clamped


def test_no_draws_lowers_and_half_weight_shrinks():
    rows = [row(i, draw=False) for i in range(20)]
    full = draw_factors(rows, window=4, weight=1.0)
    half = draw_factors(rows, window=4, weight=0.5)
    assert full[-1] == pytest.approx(0.80) and half[-1] == pytest.approx(0.80)
    rows = [row(i, draw=i % 4 == 0) for i in range(20)]  # matches the 25% prediction
    assert draw_factors(rows, window=8, weight=1.0)[-1] == pytest.approx(1.0)


def test_leagues_do_not_mix():
    rows = [row(i, draw=True, league="a") for i in range(10)] + [
        row(i, draw=False, league="b") for i in range(10)
    ]
    k = draw_factors(rows, window=4, weight=1.0)
    assert k[9] > 1 and k[19] < 1


def test_apply_renormalises():
    p = apply_draw_factor(np.array([[0.5, 0.25, 0.25]]), np.array([1.2]))
    assert p.sum() == pytest.approx(1.0) and p[0, 1] == pytest.approx(0.3 / 1.05)
