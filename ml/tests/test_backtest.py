from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from edge_ml.backtest import BacktestConfig, evaluate, walk_forward
from edge_ml.core import MatchResult, Probabilities1X2
from edge_ml.forecasters import (
    BacktestMatch,
    BaseRateForecaster,
    EloOnlyForecaster,
    MarketForecaster,
    ModelForecaster,
)
from edge_ml.poisson import probabilities_from_expected_goals

START = datetime(2022, 8, 6, 14, tzinfo=UTC)
TEAMS = {f"T{i:02d}": s for i, s in enumerate(np.linspace(-0.45, 0.45, 12))}


def synthetic_league(seasons: int = 3, seed: int = 7) -> list[BacktestMatch]:
    """Matches simulated from known strengths, with fair 'market' odds attached."""
    rng = np.random.default_rng(seed)
    names = sorted(TEAMS)
    out = []
    for s in range(seasons):
        label = f"{2022 + s}-{(23 + s) % 100:02d}"
        day = 0
        for h in names:
            for a in names:
                if h == a:
                    continue
                lam_h = float(np.exp(0.35 + TEAMS[h] - TEAMS[a]))
                lam_a = float(np.exp(0.1 + TEAMS[a] - TEAMS[h]))
                kickoff = START + timedelta(days=300 * s + day)
                day += 2
                p = probabilities_from_expected_goals(lam_h, lam_a).as_tuple()
                result = MatchResult(
                    h, a, int(rng.poisson(lam_h)), int(rng.poisson(lam_a)), kickoff, label
                )
                out.append(BacktestMatch(result, odds=tuple(1 / (x * 1.05) for x in p)))
    return out


MATCHES = synthetic_league()
EVAL_START = MATCHES[132].result.kickoff_at  # after one full season (132 matches)


class SpyForecaster:
    """Records what it was allowed to see, to prove there is no look-ahead."""

    name = "spy"

    def __init__(self):
        self.as_of = None
        self.violations = 0

    def fit(self, history, as_of):
        self.as_of = as_of
        self.violations += sum(1 for m in history if m.kickoff_at >= as_of)
        return self

    def predict(self, match):
        if match.result.kickoff_at < self.as_of:
            self.violations += 1
        return Probabilities1X2(0.4, 0.3, 0.3)


def config(**kw):
    return BacktestConfig(eval_start=EVAL_START, min_history=100, bootstrap_resamples=300, **kw)


def test_walk_forward_never_sees_the_future():
    spy = SpyForecaster()
    preds = walk_forward(MATCHES, [spy], config())
    assert spy.violations == 0
    assert len(preds.matches) == len(MATCHES) - 132
    assert all(m.result.kickoff_at >= EVAL_START for m in preds.matches)


def test_forecasters_are_scored_on_a_common_sample():
    no_odds = [BacktestMatch(m.result, None) if i % 5 == 0 else m for i, m in enumerate(MATCHES)]
    preds = walk_forward(no_odds, [BaseRateForecaster(), MarketForecaster()], config())
    assert preds.skipped["market"] > 0
    assert len(preds.probs["base_rate"]) == len(preds.probs["market"]) == len(preds.matches)
    assert all(m.odds is not None for m in preds.matches)


def test_min_history_is_respected():
    preds = walk_forward(
        MATCHES, [BaseRateForecaster()], config(eval_end=EVAL_START + timedelta(days=30))
    )
    late = BacktestConfig(eval_start=EVAL_START, min_history=10_000)
    assert len(preds.matches) > 0
    assert len(walk_forward(MATCHES, [BaseRateForecaster()], late).matches) == 0


def test_skill_ordering_on_simulated_data():
    forecasters = [
        BaseRateForecaster(),
        EloOnlyForecaster(),
        ModelForecaster("poisson_elo"),
        MarketForecaster(),
    ]
    report = evaluate(
        walk_forward(MATCHES, forecasters, config(reference="base_rate")),
        config(reference="base_rate"),
    )
    ll = {k: v["log_loss"]["mean"] for k, v in report["models"].items()}
    # the market here is the true generating probability: nothing should beat it
    assert ll["market"] <= min(ll.values()) + 1e-12
    assert ll["poisson_elo"] < ll["base_rate"]
    vs = report["models"]["poisson_elo"]["vs_reference"]["log_loss"]
    assert vs["mean_diff"] < 0 and vs["ci_low"] < vs["mean_diff"] < vs["ci_high"]


def test_report_structure_and_consistency():
    cfg = config(reference="base_rate")
    report = evaluate(walk_forward(MATCHES, [BaseRateForecaster(), EloOnlyForecaster()], cfg), cfg)
    assert report["n_matches"] == len(MATCHES) - 132
    assert sum(report["observed_frequency"].values()) == pytest.approx(1.0)
    m = report["models"]["elo_only"]
    assert set(m["per_season"]) == {"2023-24", "2024-25"}
    assert sum(s["n"] for s in m["per_season"].values()) == report["n_matches"]
    assert m["log_loss"]["ci_low"] < m["log_loss"]["mean"] < m["log_loss"]["ci_high"]
    assert sum(m["mean_predicted"].values()) == pytest.approx(1.0)
    assert len(m["calibration"]) == 30


def test_backtest_is_reproducible():
    cfg = config()
    a = evaluate(walk_forward(MATCHES, [ModelForecaster("m")], cfg), cfg)
    b = evaluate(walk_forward(MATCHES, [ModelForecaster("m")], cfg), cfg)
    assert a == b
