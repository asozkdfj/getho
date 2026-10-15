import numpy as np
import pytest

from edge_ml.poisson import outcome_probabilities, probabilities_from_expected_goals, score_matrix


@pytest.mark.parametrize(
    ("lam_h", "lam_a"), [(1.5, 1.1), (0.3, 3.2), (2.8, 0.4), (1.0, 1.0), (0.15, 0.15)]
)
def test_score_matrix_sums_to_one(lam_h, lam_a):
    m = score_matrix(lam_h, lam_a)
    assert m.shape == (11, 11)
    assert m.sum() == pytest.approx(1.0, abs=1e-12)
    assert (m >= 0).all()


@pytest.mark.parametrize(("lam_h", "lam_a"), [(1.5, 1.1), (0.3, 3.2), (2.8, 0.4), (1.0, 1.0)])
def test_1x2_probabilities_sum_to_one(lam_h, lam_a):
    p = probabilities_from_expected_goals(lam_h, lam_a)
    assert sum(p.as_tuple()) == pytest.approx(1.0, abs=1e-12)


def test_symmetric_lambdas_give_symmetric_probabilities():
    p = probabilities_from_expected_goals(1.3, 1.3)
    assert p.home == pytest.approx(p.away, abs=1e-12)


def test_stronger_home_side_is_favoured():
    p = probabilities_from_expected_goals(2.2, 0.8)
    assert p.home > p.away
    assert p.home > p.draw


def test_known_value_matches_closed_form():
    # P(0-0) for independent Poisson = exp(-(lh+la)); truncation error negligible
    m = score_matrix(1.2, 0.9, max_goals=15)
    assert m[0, 0] == pytest.approx(np.exp(-2.1), rel=1e-9)


def test_outcome_probabilities_on_handmade_matrix():
    m = np.array([[0.2, 0.1], [0.3, 0.4]])  # rows=home goals, cols=away goals
    p = outcome_probabilities(m)
    assert (p.home, p.draw, p.away) == pytest.approx((0.3, 0.6, 0.1))


def test_dixon_coles_keeps_normalisation_and_moves_draw_mass():
    plain = probabilities_from_expected_goals(1.3, 1.1)
    dc = probabilities_from_expected_goals(1.3, 1.1, rho=-0.1)
    assert sum(dc.as_tuple()) == pytest.approx(1.0)
    assert dc.draw > plain.draw  # negative rho inflates 0-0 / 1-1


@pytest.mark.parametrize(("lam_h", "lam_a"), [(0, 1), (1, -1)])
def test_invalid_lambdas_raise(lam_h, lam_a):
    with pytest.raises(ValueError):
        score_matrix(lam_h, lam_a)
