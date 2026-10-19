from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from edge_ml.shots import MIN_MATCHES, WINDOW, ShotHistory

T0 = datetime(2024, 8, 1, 15, tzinfo=UTC)


def _history(n: int = 30) -> ShotHistory:
    h = ShotHistory()
    for i in range(n):
        at = T0 + timedelta(days=7 * i)
        # A shoots a lot but scores little; B the other way round
        h.add(at, "a", "b", 1, 2, 8.0, 3.0)
        h.add(at + timedelta(days=1), "c", "d", 1, 1, 4.0, 4.0)
    return h.freeze()


def test_only_matches_finished_three_hours_before_the_cutoff_count():
    h = _history(MIN_MATCHES)
    last = T0 + timedelta(days=7 * (MIN_MATCHES - 1))
    # the 5th match kicked off 2 h before the cutoff: not finished long enough
    assert not h.features("a", last + timedelta(hours=2), "sot").any()
    assert h.features("a", last + timedelta(hours=3, minutes=1), "sot").any()


def test_too_little_history_is_neutral_and_shapes_follow_the_variant():
    h = _history(MIN_MATCHES - 1)
    late = T0 + timedelta(days=365)
    assert h.features("a", late, "sot").tolist() == [0.0, 0.0]
    assert h.features("a", late, "sot_and_finishing").shape == (4,)
    assert h.features("nobody", late, "finishing").tolist() == [0.0, 0.0]
    with pytest.raises(ValueError):
        _history().features("a", late, "xg")


def test_signs_describe_shooting_and_finishing():
    h = _history()
    late = T0 + timedelta(days=7 * 40)
    sot_a, sot_b = h.features("a", late, "sot"), h.features("b", late, "sot")
    assert sot_a[0] > 0 > sot_b[0]  # A creates more shots on target than the league
    assert sot_a[1] < 0 < sot_b[1]  # and allows fewer
    fin_a, fin_b = h.features("a", late, "finishing"), h.features("b", late, "finishing")
    assert fin_a[0] < 0 < fin_b[0]  # A scores below its shots, B above
    combined = h.features("a", late, "sot_and_finishing")
    assert np.allclose(combined, np.concatenate([sot_a, fin_a]))


def test_window_uses_only_the_last_matches():
    h = ShotHistory()
    for i in range(WINDOW + 5):
        sot = 1.0 if i < 5 else 9.0  # the first five are outside the window
        h.add(T0 + timedelta(days=7 * i), "a", "b", 1, 1, sot, 4.0)
    h.freeze()
    late = T0 + timedelta(days=7 * (WINDOW + 6))
    window_only = ShotHistory()
    for i in range(5, WINDOW + 5):
        window_only.add(T0 + timedelta(days=7 * i), "a", "b", 1, 1, 9.0, 4.0)
    for i in range(5):
        window_only.add(T0 + timedelta(days=7 * i), "x", "y", 1, 1, 1.0, 4.0)
    window_only.freeze()
    # same team window, same league pool: identical features
    assert np.allclose(h.features("a", late, "sot"), window_only.features("a", late, "sot"))
