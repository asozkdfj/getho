import numpy as np
import pytest

from edge_ml.goal_markets import (
    handicap_probability,
    handicap_shares,
    over_probability,
    profit,
    settle,
    two_way_devig,
)
from edge_ml.poisson import score_matrix


@pytest.mark.parametrize(
    ("diff", "line", "expected"),
    [
        (1, -0.5, (1.0, 0.0)),  # win by one, -0.5: win
        (0, -0.5, (0.0, 1.0)),
        (1, -1.0, (0.0, 0.0)),  # whole line: push
        (2, -1.0, (1.0, 0.0)),
        (1, -0.75, (0.5, 0.0)),  # half on -0.5 wins, half on -1 pushes
        (0, -0.25, (0.0, 0.5)),  # half on 0 pushes, half on -0.5 loses
        (0, 0.25, (0.5, 0.0)),
        (-1, 0.75, (0.0, 0.5)),
        (-1, 1.5, (1.0, 0.0)),
        (3, -2.75, (0.5, 0.0)),  # half on -2.5 wins, half on -3 pushes
        (4, -2.75, (1.0, 0.0)),
    ],
)
def test_settlement(diff, line, expected):
    assert settle(diff, line) == expected


def test_sides_mirror_each_other():
    for diff in range(-3, 4):
        for line in (-1.75, -1.0, -0.25, 0.0, 0.5, 1.25):
            home = settle(diff, line)
            away = settle(-diff, -line)
            assert home == (away[1], away[0])


def test_probabilities_from_a_score_matrix():
    m = score_matrix(1.6, 1.1)
    # over 2.5 = 1 - P(total <= 2) with total ~ Poisson(2.7) (independent Poisson)
    from scipy.stats import poisson

    assert over_probability(m) == pytest.approx(1 - poisson.cdf(2, 2.7), abs=1e-6)
    # level ball (0): pushes on draws, so P = P(home win) / (P(home) + P(away))
    i, j = np.indices(m.shape)
    home, away = m[i > j].sum(), m[i < j].sum()
    assert handicap_probability(m, 0.0) == pytest.approx(home / (home + away))
    # -0.5 has no push: P(home win)
    assert handicap_probability(m, -0.5) == pytest.approx(home)
    won, lost = handicap_shares(m, -0.75)
    assert 0 < won < 1 and 0 < lost < 1 and won + lost < 1  # some pushes


def test_fair_price_has_zero_expected_profit():
    m = score_matrix(1.4, 1.2)
    won, lost = handicap_shares(m, -0.25)
    fair = 1 / handicap_probability(m, -0.25)
    assert won * (fair - 1) - lost == pytest.approx(0, abs=1e-12)


def test_devig_and_profit():
    assert two_way_devig(1.9, 1.9) == pytest.approx(0.5)
    assert two_way_devig(1.5, 2.5) == pytest.approx((1 / 1.5) / (1 / 1.5 + 1 / 2.5))
    assert profit(1.0, 0.0, 1.9) == pytest.approx(0.9)
    assert profit(0.5, 0.0, 1.9) == pytest.approx(0.45)
    assert profit(0.0, 0.5, 1.9) == pytest.approx(-0.5)
    assert profit(0.0, 0.0, 1.9) == 0.0
