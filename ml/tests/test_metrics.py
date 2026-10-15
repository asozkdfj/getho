import math

import numpy as np
import pytest

from edge_ml.metrics import (
    accuracy_per_match,
    bootstrap_mean_ci,
    brier_per_match,
    calibration_bins,
    expected_calibration_error,
    log_loss_per_match,
    rps_per_match,
)

Y = np.array([0, 1, 2, 0])


def test_perfect_forecast_scores_zero():
    p = np.eye(3)[Y]
    assert log_loss_per_match(p, Y) == pytest.approx(np.zeros(4), abs=1e-12)
    assert brier_per_match(p, Y) == pytest.approx(np.zeros(4))
    assert rps_per_match(p, Y) == pytest.approx(np.zeros(4))
    assert accuracy_per_match(p, Y).mean() == 1.0


def test_uniform_forecast_known_values():
    p = np.full((4, 3), 1 / 3)
    assert log_loss_per_match(p, Y) == pytest.approx(np.full(4, math.log(3)))
    assert brier_per_match(p, Y) == pytest.approx(np.full(4, 2 / 3))
    # RPS for uniform: home win -> ((1/3-1)^2 + (2/3-1)^2)/2 = 5/18 ; draw -> 1/9 ; away -> 5/18
    assert rps_per_match(p, Y) == pytest.approx([5 / 18, 1 / 9, 5 / 18, 5 / 18])


def test_rps_rewards_near_misses():
    # true outcome AWAY; predicting DRAW is "closer" than predicting HOME
    near = rps_per_match(np.array([[0.0, 1.0, 0.0]]), np.array([2]))
    far = rps_per_match(np.array([[1.0, 0.0, 0.0]]), np.array([2]))
    assert near[0] < far[0]


def test_wrong_confident_forecast_is_penalised_heavily():
    assert log_loss_per_match(np.array([[0.98, 0.01, 0.01]]), np.array([2]))[0] > 4


def test_calibration_bins_cover_every_prediction():
    rng = np.random.default_rng(0)
    p = rng.dirichlet([2, 1, 1.5], size=500)
    y = np.array([rng.choice(3, p=row) for row in p])
    bins = calibration_bins(p, y)
    for outcome in ("HOME", "DRAW", "AWAY"):
        assert sum(b.count for b in bins if b.outcome == outcome) == 500
    # outcomes drawn from the forecasts themselves -> well calibrated
    assert expected_calibration_error(p, y) < 0.05


def test_miscalibration_is_detected():
    y = np.array([0] * 50 + [2] * 50)  # home wins only half the time
    p = np.tile([0.9, 0.05, 0.05], (100, 1))  # but we always say 90%
    assert expected_calibration_error(p, y) > 0.25


def test_bootstrap_ci_contains_mean_and_is_deterministic():
    v = np.random.default_rng(1).normal(1.0, 0.5, 300)
    lo, hi = bootstrap_mean_ci(v)
    assert lo < v.mean() < hi
    assert bootstrap_mean_ci(v) == (lo, hi)


def test_inputs_are_validated():
    with pytest.raises(ValueError):
        log_loss_per_match(np.array([[0.5, 0.5, 0.5]]), np.array([0]))
    with pytest.raises(ValueError):
        brier_per_match(np.full((2, 3), 1 / 3), np.array([0]))
