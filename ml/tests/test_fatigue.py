from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from edge_ml.fatigue import (
    REST_CAP_DAYS,
    VARIANTS,
    Appearance,
    Schedule,
    adjust,
    congestion,
    fit,
    rest_deficit,
)
from edge_ml.metrics import cluster_bootstrap_ci

SAT = datetime(2024, 3, 16, 15, 0, tzinfo=UTC)


def app(days_before: float, comp: str = "league", et: bool = False, team: str = "A"):
    return Appearance(team, SAT - timedelta(days=days_before), comp, et)


def test_features_use_only_earlier_days():
    schedule = Schedule([app(3, "cl", et=True), app(7), app(10, "facup"), app(-4)])
    f = schedule.features("A", SAT)
    assert f.rest_days == 3
    assert (f.load_7, f.load_14, f.load_28) == (2, 3, 3)  # the match 4 days later is ignored
    assert f.extra_time_4d and f.europe_4d


def test_same_day_match_is_not_its_own_history():
    schedule = Schedule([app(0), app(5)])
    assert schedule.features("A", SAT).rest_days == 5


def test_unknown_team_and_long_breaks_are_fully_rested():
    schedule = Schedule([app(40)])
    assert schedule.features("B", SAT).rest_days == REST_CAP_DAYS
    f = schedule.features("A", SAT)
    assert f.rest_days == REST_CAP_DAYS and f.load_28 == 0


def test_duplicate_listings_count_once():
    schedule = Schedule([app(3, "facup"), app(3, "facup")])
    assert schedule.features("A", SAT).load_7 == 1


def test_variant_scales():
    rested = Schedule([app(8)]).features("A", SAT)
    tired = Schedule([app(3), app(6), app(10), app(13)]).features("A", SAT)
    assert rest_deficit(rested) == 0 and rest_deficit(tired) == 1
    assert congestion(rested) == pytest.approx(-0.5) and congestion(tired) == 1
    assert [len(fn(tired)) for fn in VARIANTS.values()] == [1, 1, 3]


def test_zero_coefficients_change_nothing():
    lam = np.array([1.4, 0.9])
    x = np.array([[1.0], [0.0]])
    h, a = adjust(lam, lam[::-1], x, x[::-1], [0.0], [0.0])
    assert np.allclose(h, lam) and np.allclose(a, lam[::-1])


def test_fit_recovers_simulated_effects():
    rng = np.random.default_rng(3)
    n = 6000
    lam_h, lam_a = rng.uniform(1.0, 2.0, n), rng.uniform(0.7, 1.5, n)
    x_h, x_a = rng.uniform(0, 1, (n, 1)), rng.uniform(0, 1, (n, 1))
    true_h, true_a = adjust(lam_h, lam_a, x_h, x_a, [-0.2], [0.1])
    result = fit(lam_h, lam_a, x_h, x_a, rng.poisson(true_h), rng.poisson(true_a))
    assert result.own[0] == pytest.approx(-0.2, abs=0.06)
    assert result.opponent[0] == pytest.approx(0.1, abs=0.06)
    assert result.log_likelihood_gain > 0


def test_fit_finds_nothing_in_noise():
    rng = np.random.default_rng(4)
    n = 6000
    lam_h, lam_a = rng.uniform(1.0, 2.0, n), rng.uniform(0.7, 1.5, n)
    x_h, x_a = rng.uniform(0, 1, (n, 1)), rng.uniform(0, 1, (n, 1))
    result = fit(lam_h, lam_a, x_h, x_a, rng.poisson(lam_h), rng.poisson(lam_a))
    assert abs(result.own[0]) < 0.06 and abs(result.opponent[0]) < 0.06


def test_cluster_bootstrap_widens_for_correlated_matches():
    rng = np.random.default_rng(5)
    week_effect = np.repeat(rng.normal(0, 1, 50), 10)  # 10 matches share a week
    values = week_effect + rng.normal(0, 0.1, 500)
    weeks = np.repeat(np.arange(50), 10).tolist()
    lo, hi = cluster_bootstrap_ci(values, weeks)
    naive = 1.96 * values.std() / np.sqrt(len(values))
    assert (hi - lo) / 2 > 2 * naive  # pretending matches are independent understates it
    with pytest.raises(ValueError):
        cluster_bootstrap_ci(values, weeks[:10])
