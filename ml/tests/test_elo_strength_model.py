from datetime import UTC, datetime, timedelta

import pytest

from edge_ml.calibration import Calibrator, IdentityCalibrator
from edge_ml.combination import Leg, combine
from edge_ml.core import MatchResult, Outcome, Probabilities1X2
from edge_ml.elo import EloRatings, expected_score, goal_difference_multiplier
from edge_ml.model import PoissonEloModel
from edge_ml.strength import fit_strengths

T0 = datetime(2026, 8, 1, 14, 0, tzinfo=UTC)


def _season(n_rounds: int = 6) -> list[MatchResult]:
    """STRONG beats everybody, WEAK loses to everybody, MID draws."""
    out = []
    for r in range(n_rounds):
        t = T0 + timedelta(days=7 * r)
        out += [
            MatchResult("STRONG", "WEAK", 3, 0, t),
            MatchResult("MID", "STRONG", 0, 2, t),
            MatchResult("WEAK", "MID", 1, 1, t + timedelta(hours=3)),
        ]
    return out


def test_expected_score_properties():
    assert expected_score(1500, 1500) == pytest.approx(0.5)
    assert expected_score(1600, 1500) + expected_score(1500, 1600) == pytest.approx(1.0)
    assert expected_score(1500, 1500, home_advantage=60) > 0.5


def test_goal_difference_multiplier():
    assert goal_difference_multiplier(0) == 1.0
    assert goal_difference_multiplier(1) == 1.0
    assert goal_difference_multiplier(3) > goal_difference_multiplier(2) > 1.0


def test_elo_is_zero_sum_and_orders_teams():
    elo = EloRatings().fit(_season())
    assert sum(elo.ratings.values()) == pytest.approx(1500 * 3)
    assert elo.rating("STRONG") > elo.rating("MID") > elo.rating("WEAK")


def test_elo_fit_is_order_independent_of_input_list():
    matches = _season()
    a = EloRatings().fit(matches)
    b = EloRatings().fit(list(reversed(matches)))
    assert a.ratings == pytest.approx(b.ratings)


def test_strengths_order_teams_and_ignore_future_matches():
    matches = _season()
    as_of = T0 + timedelta(days=100)
    s = fit_strengths(matches, as_of)
    assert s.attack["STRONG"] > s.attack["MID"]
    assert s.defence["WEAK"] > s.defence["STRONG"]  # weak concedes more
    future = [*matches, MatchResult("WEAK", "STRONG", 9, 0, as_of + timedelta(days=1))]
    s2 = fit_strengths(future, as_of)
    assert s2.attack == pytest.approx(s.attack)


def test_strengths_without_data_fall_back_to_league_average():
    s = fit_strengths([], T0)
    lh, la = s.expected_goals("A", "B")
    assert lh > la > 0


def test_model_predictions_sum_to_one_and_are_sensible():
    model = PoissonEloModel().fit(_season(), as_of=T0 + timedelta(days=60))
    out = model.predict("STRONG", "WEAK")
    assert sum(out.probabilities.as_tuple()) == pytest.approx(1.0, abs=1e-9)
    assert out.probabilities.home > 0.6
    rev = model.predict("WEAK", "STRONG")
    assert rev.probabilities.away > rev.probabilities.home
    assert out.features["training_matches"] == 18


def test_model_is_deterministic():
    as_of = T0 + timedelta(days=60)
    a = PoissonEloModel().fit(_season(), as_of).predict("MID", "WEAK")
    b = PoissonEloModel().fit(_season(), as_of).predict("MID", "WEAK")
    assert a == b


def test_model_requires_fit():
    with pytest.raises(RuntimeError):
        PoissonEloModel().predict("A", "B")


def test_identity_calibrator():
    cal = IdentityCalibrator()
    assert isinstance(cal, Calibrator)
    p = Probabilities1X2(0.5, 0.3, 0.2)
    assert cal.fit([p], [Outcome.HOME]).calibrate(p) == pytest.approx(p)
    with pytest.raises(ValueError):
        cal.fit([p], [])


def test_probabilities_validation():
    with pytest.raises(ValueError):
        Probabilities1X2(0.5, 0.5, 0.5)
    assert Probabilities1X2.normalized(2, 1, 1).home == pytest.approx(0.5)
    assert Probabilities1X2(0.5, 0.3, 0.2).get(Outcome.DRAW) == 0.3


def test_combination_independence_product():
    legs = [Leg(0.5, 0.45, 2.1), Leg(0.6, 0.62, 1.55), Leg(0.3, 0.28, 3.4)]
    res = combine(legs)
    assert res.model_probability == pytest.approx(0.5 * 0.6 * 0.3)
    assert res.fair_market_probability == pytest.approx(0.45 * 0.62 * 0.28)
    assert res.combined_odds == pytest.approx(2.1 * 1.55 * 3.4)
    assert res.expected_value == pytest.approx(res.model_probability * res.combined_odds - 1)
    assert res.method == "independence_approximation"


@pytest.mark.parametrize("n", [0, 1, 4])
def test_combination_leg_count_limits(n):
    with pytest.raises(ValueError):
        combine([Leg(0.5, 0.5, 2.0)] * n)
