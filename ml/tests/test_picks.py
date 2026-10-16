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


def test_decision_hour_drops_started_matches_and_late_predictions():
    # KST kickoffs 02:00, 09:00, 20:00 and 21:00 on the 17th; the 21:00 prediction
    # only becomes available at 10:00 KST, after the 09:00 decision.
    kst_midnight = datetime(2026, 10, 16, 15, tzinfo=UTC)
    kickoffs = [kst_midnight + timedelta(hours=h) for h in (2, 9, 20, 21)]
    probs = np.array([[0.9, 0.05, 0.05], [0.8, 0.1, 0.1], [0.6, 0.2, 0.2], [0.7, 0.2, 0.1]])
    ready = [kst_midnight] * 3 + [kst_midnight + timedelta(hours=10)]
    whole_day, at_nine = (
        backtest_daily_picks(
            ["a", "b", "c", "d"],
            kickoffs,
            probs,
            np.array([0, 0, 1, 0]),
            [0.55],
            decision_hour=hour,
            prediction_times=ready if hour is not None else None,
        )[0]
        for hour in (None, 9)
    )
    assert whole_day["eligible_matches"] == 4 and whole_day["hits"] == 1  # picks "a" (90%)
    assert at_nine["eligible_matches"] == 1 and at_nine["hits"] == 0  # only "c" is left
    assert at_nine["mean_pick_probability"] == pytest.approx(0.6)
    assert at_nine["coverage"] == 1.0


def test_days_without_candidates_count_against_coverage():
    kickoff = [datetime(2026, 10, 16, 16, tzinfo=UTC)]  # 01:00 KST, before 09:00
    row = backtest_daily_picks(
        ["a"], kickoff, np.array([[0.9, 0.05, 0.05]]), np.array([0]), [0.55], decision_hour=9
    )[0]
    assert row["match_days"] == 1 and row["coverage"] == 0 and row["hit_rate"] is None


def test_misaligned_or_ambiguous_inputs_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        backtest_daily_picks(["a", "a"], [T, T], np.ones((2, 3)), np.array([0, 0]), [0.55])
    with pytest.raises(ValueError, match="align"):
        backtest_daily_picks(["a"], [T, T], np.ones((2, 3)), np.array([0, 0]), [0.55])
    with pytest.raises(ValueError, match="timezone"):
        naive = datetime(2026, 10, 17, 11)  # noqa: DTZ001 - deliberately naive
        backtest_daily_picks(["a"], [naive], np.ones((1, 3)), np.array([0]), [0.55])
