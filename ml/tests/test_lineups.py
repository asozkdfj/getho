from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch, MatchLineups, TeamSheet
from edge_ml.lineups import (
    LineupForecaster,
    LineupIndex,
    adjust,
    fit_coefficients,
    player_weights,
    strengths_for,
    xi_strength,
)
from edge_ml.model import ModelParams

T0 = datetime(2026, 1, 1, tzinfo=UTC)
XI = tuple(f"p{i}" for i in range(11))


def sheet(starters=XI, subs=()):
    minutes = dict.fromkeys(starters, 90)
    minutes.update(dict.fromkeys(subs, 20))
    return TeamSheet(tuple(starters), minutes)


def test_weights_are_minute_shares_and_usual_xi_is_full_strength():
    w = player_weights([sheet(), sheet()])
    assert w["p0"] == pytest.approx(1.0)
    assert xi_strength(XI, w) == pytest.approx(1.0)
    rotated = (*XI[:9], "new1", "new2")  # two regulars rested for unknown players
    assert xi_strength(rotated, w) == pytest.approx(9 / 11)
    assert xi_strength(XI, {}) == 1.0  # no history -> no adjustment


def test_adjustment_direction():
    lam_h, lam_a = adjust(1.5, 1.2, s_h=0.8, s_a=1.0, beta=0.3, gamma=0.2)
    assert lam_h < 1.5  # weakened home XI scores less ...
    assert lam_a > 1.2  # ... and concedes more
    assert adjust(1.5, 1.2, 1.0, 1.0, 0.3, 0.2) == (1.5, 1.2)


def test_strengths_use_only_given_history():
    m = BacktestMatch(MatchResult("A", "B", 1, 0, T0, "s"), lineups=MatchLineups(sheet(), sheet()))
    assert strengths_for(m, {}) == (1.0, 1.0)  # fewer than 3 past matches -> neutral
    assert strengths_for(BacktestMatch(m.result), {}) is None  # no line-up -> cannot predict


def test_coefficient_fit_recovers_a_known_effect():
    rng = np.random.default_rng(1)
    n = 6000
    lam_h, lam_a = rng.uniform(0.8, 2.0, n), rng.uniform(0.6, 1.6, n)
    s_h, s_a = rng.uniform(0.6, 1.0, n), rng.uniform(0.6, 1.0, n)
    beta, gamma = 0.4, 0.25
    g_h = rng.poisson(lam_h * np.exp(beta * (s_h - 1) - gamma * (s_a - 1)))
    g_a = rng.poisson(lam_a * np.exp(beta * (s_a - 1) - gamma * (s_h - 1)))
    fit = fit_coefficients(np.column_stack([lam_h, lam_a, s_h, s_a, g_h, g_a]))
    assert fit.beta == pytest.approx(beta, abs=0.15) and fit.gamma == pytest.approx(gamma, abs=0.15)
    assert fit.log_likelihood_gain > 0


def test_forecaster_never_reads_future_line_ups():
    teams = ["A", "B", "C", "D"]
    matches = []
    for k in range(40):
        h, a = teams[k % 4], teams[(k + 1) % 4]
        r = MatchResult(h, a, k % 3, (k + 1) % 2, T0 + timedelta(days=k), "s")
        matches.append(BacktestMatch(r, lineups=MatchLineups(sheet(), sheet())))
    f = LineupForecaster("x", ModelParams(), LineupIndex.build(matches), beta=0.3, gamma=0.2)
    as_of = T0 + timedelta(days=20)
    f.fit([m.result for m in matches if m.result.kickoff_at < as_of], as_of)
    assert all(len(v) <= 10 for v in f._recent.values())
    p = f.predict(matches[25])
    assert p is not None and sum(p.as_tuple()) == pytest.approx(1.0)
