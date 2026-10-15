import pytest

from edge_ml.market import devig, implied_probabilities, market_view_1x2, overround
from edge_ml.value import edge, exceeds_threshold, expected_value

BOOKS = [
    (2.10, 3.40, 3.60),
    (1.25, 6.50, 11.0),
    (4.20, 3.75, 1.85),
    (2.90, 2.90, 2.90),
    (3.00, 3.00, 3.00),  # fair book, zero margin
]


@pytest.mark.parametrize("odds", BOOKS)
def test_devig_sums_to_one(odds):
    fair = devig(odds)
    assert sum(fair) == pytest.approx(1.0, abs=1e-12)
    assert all(0 < p < 1 for p in fair)


@pytest.mark.parametrize("odds", BOOKS)
def test_devig_preserves_ordering(odds):
    fair = devig(odds)
    implied = implied_probabilities(odds)
    assert sorted(range(3), key=lambda i: fair[i]) == sorted(range(3), key=lambda i: implied[i])


def test_overround_known_value():
    # 1/2.1 + 1/3.4 + 1/3.6 = 1.048086...
    assert overround((2.10, 3.40, 3.60)) == pytest.approx(0.0480859, abs=1e-6)
    assert overround((3.0, 3.0, 3.0)) == pytest.approx(0.0, abs=1e-12)


def test_market_view_fields_consistent():
    mv = market_view_1x2(2.10, 3.40, 3.60)
    assert sum(mv.fair.as_tuple()) == pytest.approx(1.0)
    assert sum(mv.implied_raw) == pytest.approx(1.0 + mv.overround)


@pytest.mark.parametrize("bad", [(1.0, 3.0, 3.0), (0.5, 3.0, 3.0), (float("nan"), 2, 2), (2.0,)])
def test_invalid_odds_raise(bad):
    with pytest.raises(ValueError):
        devig(bad)


def test_edge_and_ev_formulas():
    assert edge(0.55, 0.50) == pytest.approx(0.05)
    assert expected_value(0.55, 2.0) == pytest.approx(0.10)
    assert expected_value(0.5, 2.0) == pytest.approx(0.0)
    assert expected_value(0.4, 2.0) == pytest.approx(-0.2)


def test_ev_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        expected_value(1.2, 2.0)
    with pytest.raises(ValueError):
        expected_value(0.5, 1.0)


def test_threshold_requires_both_edge_and_ev():
    assert exceeds_threshold(0.04, 0.05, 0.03)
    assert not exceeds_threshold(0.04, 0.01, 0.03)
    assert not exceeds_threshold(0.01, 0.05, 0.03)
