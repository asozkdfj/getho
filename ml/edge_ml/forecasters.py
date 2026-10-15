"""Interchangeable 1X2 forecasters for like-for-like backtests.

Every forecaster is fitted on matches strictly before ``as_of`` and predicts
matches at or after it. ``predict`` may return None when it cannot forecast a
match (e.g. the market forecaster without odds); the backtest then evaluates
all forecasters only on matches every one of them could predict.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from edge_ml.core import MatchResult, Probabilities1X2
from edge_ml.elo import EloParams, EloRatings
from edge_ml.market import devig
from edge_ml.model import ModelParams, PoissonEloModel
from edge_ml.poisson import probabilities_from_expected_goals


@dataclass(frozen=True, slots=True)
class BacktestMatch:
    """A finished match plus (optionally) the market prices available before kickoff."""

    result: MatchResult
    odds: tuple[float, float, float] | None = None

    @property
    def outcome_index(self) -> int:
        r = self.result
        if r.home_goals > r.away_goals:
            return 0
        if r.home_goals == r.away_goals:
            return 1
        return 2


class Forecaster(Protocol):
    name: str

    def fit(self, history: Sequence[MatchResult], as_of: datetime) -> Forecaster: ...

    def predict(self, match: BacktestMatch) -> Probabilities1X2 | None: ...


@dataclass(slots=True)
class BaseRateForecaster:
    """Historical home/draw/away frequencies (with Laplace smoothing)."""

    name: str = "base_rate"
    probs: Probabilities1X2 = field(default_factory=lambda: Probabilities1X2(0.45, 0.25, 0.30))

    def fit(self, history: Sequence[MatchResult], as_of: datetime) -> BaseRateForecaster:
        counts = [1.0, 1.0, 1.0]
        for m in history:
            k = 0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
            counts[k] += 1
        self.probs = Probabilities1X2.normalized(*counts)
        return self

    def predict(self, match: BacktestMatch) -> Probabilities1X2:
        return self.probs


@dataclass(slots=True)
class EloOnlyForecaster:
    """Elo rating difference -> goal supremacy around the league-average total."""

    name: str = "elo_only"
    params: EloParams = field(default_factory=EloParams)
    elo_points_per_goal: float = 280.0
    min_lambda: float = 0.15
    _elo: EloRatings | None = None
    _total: float = 2.8

    def fit(self, history: Sequence[MatchResult], as_of: datetime) -> EloOnlyForecaster:
        self._elo = EloRatings(params=self.params).fit(history)
        if history:
            self._total = sum(m.home_goals + m.away_goals for m in history) / len(history)
        return self

    def predict(self, match: BacktestMatch) -> Probabilities1X2:
        assert self._elo is not None
        s = self._elo.rating_difference(match.result.home, match.result.away)
        s /= self.elo_points_per_goal
        lam_h = max((self._total + s) / 2, self.min_lambda)
        lam_a = max((self._total - s) / 2, self.min_lambda)
        return probabilities_from_expected_goals(lam_h, lam_a)


@dataclass(slots=True)
class ModelForecaster:
    """The production model family (Poisson strengths + Elo), any parameters."""

    name: str
    params: ModelParams = field(default_factory=ModelParams)
    _model: PoissonEloModel | None = None

    def fit(self, history: Sequence[MatchResult], as_of: datetime) -> ModelForecaster:
        self._model = PoissonEloModel(params=self.params).fit(history, as_of)
        return self

    def predict(self, match: BacktestMatch) -> Probabilities1X2:
        assert self._model is not None
        return self._model.predict(match.result.home, match.result.away).probabilities


@dataclass(slots=True)
class SeasonBlindForecaster:
    """Ablation: hides season labels, which disables the promoted-team prior
    (i.e. reproduces the v0.1.0 behaviour of the same model)."""

    name: str
    params: ModelParams = field(default_factory=ModelParams)
    _model: PoissonEloModel | None = None

    def fit(self, history: Sequence[MatchResult], as_of: datetime) -> SeasonBlindForecaster:
        blind = [dataclasses.replace(m, season=None) for m in history]
        self._model = PoissonEloModel(params=self.params).fit(blind, as_of)
        return self

    def predict(self, match: BacktestMatch) -> Probabilities1X2:
        assert self._model is not None
        return self._model.predict(match.result.home, match.result.away).probabilities


@dataclass(slots=True)
class MarketForecaster:
    """De-vigged bookmaker prices (proportional). None when no odds are known."""

    name: str = "market"

    def fit(self, history: Sequence[MatchResult], as_of: datetime) -> MarketForecaster:
        return self

    def predict(self, match: BacktestMatch) -> Probabilities1X2 | None:
        if match.odds is None:
            return None
        return Probabilities1X2.normalized(*devig(match.odds))
