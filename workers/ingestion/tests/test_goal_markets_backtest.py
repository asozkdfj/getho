"""Smoke test of the goal-markets experiment on synthetic data (a code check, not evidence)."""

from datetime import UTC, datetime, timedelta

import numpy as np

from edge_ingestion.feature_experiment import Row
from edge_ingestion.goal_markets_backtest import (
    build_samples,
    calibration,
    decide,
    market_report,
    over_rate_lookup,
    weighted_log_loss,
)
from edge_ingestion.history.club_match_data import GoalMarketOdds, match_key
from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch
from edge_ml.model import ModelParams

T0 = datetime(2020, 8, 1, 14, tzinfo=UTC)


def _match(i: int, season: str, hg: int, ag: int) -> BacktestMatch:
    r = MatchResult(f"h{i % 7}", f"a{i % 5}", hg, ag, T0 + timedelta(days=i), season)
    return BacktestMatch(r, odds=(2.0, 3.4, 3.9))


def test_weighted_scores_ignore_pushes_and_halve_half_results():
    p = np.array([0.6, 0.6, 0.6])
    won, lost = np.array([1.0, 0.5, 0.0]), np.array([0.0, 0.0, 0.0])
    ll = weighted_log_loss(p, won, lost)
    assert ll[1] == ll[0] / 2 and ll[2] == 0
    cal = calibration(np.array([0.7, 0.7]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    assert cal["observed"] == 0.5 and abs(cal["mean_predicted"] - 0.7) < 1e-12


def test_experiment_runs_end_to_end_on_synthetic_matches(monkeypatch):
    rng = np.random.default_rng(0)
    seasons = ["2020-21"] * 40 + ["2023-24"] * 40
    matches = [
        _match(i, s, int(rng.poisson(1.5)), int(rng.poisson(1.1))) for i, s in enumerate(seasons)
    ]
    rows = [
        Row("en.1", m, m.result.kickoff_at - timedelta(days=1), 1.5, 1.1, (0.45, 0.27, 0.28))
        for m in matches
    ]
    lines = [-0.25, -0.5, 0.0, -1.0]
    odds = {
        match_key(m.result): GoalMarketOdds(1.9, 1.95, lines[i % 4], 1.92, 1.92)
        for i, m in enumerate(matches)
    }
    rate = over_rate_lookup(matches)
    ou, ah, dropped = build_samples(rows, odds, {"en.1": rate}, ModelParams())
    assert len(ah.rows) == 80 and dropped["no_handicap"] == 0
    assert len(ou.rows) < 80 and dropped["no_over_under"] == 80 - len(ou.rows)  # no history yet
    import edge_ingestion.goal_markets_backtest as gm

    monkeypatch.setattr(gm, "VALIDATION", ["2020-21"])
    monkeypatch.setattr(gm, "FOLLOW_UP", ["2023-24"])
    for s in (ou, ah):
        rep = market_report(s, ["en.1"])
        assert set(rep["decision"]) == {"d1_informative", "d2_calibrated", "eligible_for_display"}
        assert rep["follow_up"]["n_matches"] == 40
    assert "half_lines_follow_up" in market_report(ah, ["en.1"])["descriptive"]


def test_decision_needs_both_criteria():
    seg = {
        "naive": {"log_loss": 0.70},
        "model": {"log_loss": 0.69, "mean_predicted": 0.50, "observed": 0.51, "ece": 0.01},
        "model_vs_naive": {"log_loss_diff": -0.005, "ci95_weekly": [-0.008, -0.002]},
    }
    assert decide(seg, seg)["eligible_for_display"] is True
    off = {**seg, "model": {**seg["model"], "mean_predicted": 0.55}}
    assert decide(seg, off)["eligible_for_display"] is False
    weak = {**seg, "model_vs_naive": {"log_loss_diff": -0.001, "ci95_weekly": [-0.003, 0.001]}}
    assert decide(seg, weak)["d1_informative"]["passed"] is False
