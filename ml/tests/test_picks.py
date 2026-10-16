from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from edge_ml.core import Outcome, Probabilities1X2
from edge_ml.metrics import wilson_interval
from edge_ml.picks import PickCandidate, backtest_daily_picks, best_outcome, select_pick

T = datetime(2026, 10, 17, 11, 0, tzinfo=UTC)


def cand(key, h, d, a, hours=0):
    return PickCandidate(key, T + timedelta(hours=hours), Probabilities1X2(h, d, a))


def test_picks_highest_probability_outcome_across_matches():
    # the example from the spec: A home 74%, B home 48%, C away 60%
    choice = select_pick(
        [cand("A", 0.74, 0.17, 0.09), cand("B", 0.48, 0.29, 0.23), cand("C", 0.21, 0.19, 0.60)],
        0.55,
    )
    assert choice.candidate.key == "A" and choice.outcome is Outcome.HOME
    assert choice.probability == pytest.approx(0.74)


def test_away_and_draw_can_be_picked():
    assert select_pick([cand("C", 0.21, 0.19, 0.60)], 0.55).outcome is Outcome.AWAY
    assert best_outcome(Probabilities1X2(0.3, 0.4, 0.3))[0] is Outcome.DRAW


def test_no_pick_when_nothing_reaches_the_threshold():
    assert select_pick([cand("B", 0.48, 0.29, 0.23)], 0.55) is None
    assert select_pick([], 0.0) is None


def test_ties_are_broken_deterministically():
    a, b = cand("A", 0.6, 0.2, 0.2, hours=3), cand("B", 0.6, 0.2, 0.2, hours=1)
    assert select_pick([a, b], 0.5).candidate.key == "B"  # earlier kickoff wins
    assert select_pick([b, a], 0.5).candidate.key == "B"  # order independent


def test_daily_backtest_uses_kst_day_boundaries():
    # 14:00 UTC and 16:00 UTC on Oct 17 fall on Oct 17 and Oct 18 in KST (UTC+9)
    kick = [datetime(2026, 10, 17, 14, tzinfo=UTC), datetime(2026, 10, 17, 16, tzinfo=UTC)]
    probs = np.array([[0.7, 0.2, 0.1], [0.6, 0.2, 0.2]])
    rows = backtest_daily_picks(["a", "b"], kick, probs, np.array([0, 2]), [0.55])
    r = rows[0]
    assert (r["match_days"], r["days_with_pick"], r["hits"]) == (2, 2, 1)
    assert r["mean_pick_probability"] == pytest.approx(0.65)
    same_day_utc = backtest_daily_picks(["a", "b"], kick, probs, np.array([0, 2]), [0.55], tz="UTC")
    assert same_day_utc[0]["days_with_pick"] == 1 and same_day_utc[0]["hits"] == 1


def test_wilson_interval():
    lo, hi = wilson_interval(71, 100)
    assert lo < 0.71 < hi and 0.61 < lo < 0.63
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_timing_proxy_excludes_started_and_unavailable_predictions():
    # KST 02:00, 09:00, 20:00, 21:00. The last prediction arrives at 10:00.
    midnight = datetime(2026, 10, 17, 0, tzinfo=UTC)
    kick = [midnight + timedelta(hours=h) for h in (-7, 0, 11, 12)]
    p = np.array([[0.9, 0.05, 0.05], [0.8, 0.1, 0.1], [0.6, 0.2, 0.2], [0.7, 0.2, 0.1]])
    times = [midnight - timedelta(hours=1)] * 3 + [midnight + timedelta(hours=1)]
    row = backtest_daily_picks(
        ["a", "b", "c", "d"],
        kick,
        p,
        np.array([2, 2, 0, 2]),
        [0.55],
        decision_hour=9,
        prediction_times=times,
    )[0]
    assert row["eligible_matches"] == 1
    assert row["hits"] == 1
    assert row["mean_pick_probability"] == pytest.approx(0.6)


def test_timing_proxy_keeps_days_without_eligible_matches_in_coverage():
    kick = [datetime(2026, 10, 17, 0, tzinfo=UTC)]
    row = backtest_daily_picks(
        ["a"], kick, np.array([[0.9, 0.05, 0.05]]), np.array([0]), [0.55], decision_hour=9
    )[0]
    assert row["match_days"] == 1 and row["coverage"] == 0
    assert row["hit_rate"] is None


def test_daily_backtest_rejects_duplicate_keys():
    with pytest.raises(ValueError, match="unique"):
        backtest_daily_picks(["a", "a"], [T, T], np.ones((2, 3)), np.array([0, 0]), [0.55])
