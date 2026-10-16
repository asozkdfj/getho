"""Line-up strength as a model input (experimental, evaluated before any use).

Idea: how strong is today's starting XI compared with the team's usual one?
A coach's choices over recent matches reveal who matters: a player's share of
the minutes available in the team's last matches is his weight. The XI strength
is the weight of today's starters divided by the weight of the usual XI (the
11 heaviest players), so 1.0 = the usual XI and 0.8 = a fifth of it missing.

The production model's expected goals are then adjusted:

    log lambda_home' = log lambda_home + beta * (S_home - 1) - gamma * (S_away - 1)
    log lambda_away' = log lambda_away + beta * (S_away - 1) - gamma * (S_home - 1)

beta (own attack) and gamma (opponent's defence) are fitted by Poisson maximum
likelihood on a validation period with the production lambdas as offsets, then
frozen and scored once on a later test period (walk-forward, no look-ahead).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize

from edge_ml.core import MatchResult, Probabilities1X2
from edge_ml.forecasters import BacktestMatch, MatchLineups, TeamSheet
from edge_ml.model import ModelParams, PoissonEloModel
from edge_ml.poisson import probabilities_from_expected_goals

RECENT_MATCHES = 10
MIN_MATCHES = 3  # fewer team matches -> no adjustment (strength = 1)
FULL_MATCH = 90


def match_key(r: MatchResult) -> tuple[datetime, str, str]:
    return (r.kickoff_at, r.home, r.away)


def player_weights(sheets: Sequence[TeamSheet]) -> dict[str, float]:
    """Share of the available minutes each player played in these matches (0..1)."""
    if not sheets:
        return {}
    minutes: dict[str, float] = defaultdict(float)
    for sheet in sheets:
        for player, m in sheet.minutes.items():
            minutes[player] += m
    available = FULL_MATCH * len(sheets)
    return {p: m / available for p, m in minutes.items()}


def xi_strength(starters: Sequence[str], weights: Mapping[str, float]) -> float:
    """Weight of today's XI relative to the usual XI (1.0 = usual XI)."""
    usual = sum(sorted(weights.values(), reverse=True)[:11])
    if usual <= 0:
        return 1.0
    return min(sum(weights.get(p, 0.0) for p in starters) / usual, 1.0)


@dataclass(slots=True)
class LineupIndex:
    """Team sheets of every match, looked up only for matches in the fit history."""

    sheets: dict[tuple[datetime, str, str], MatchLineups]

    @classmethod
    def build(cls, matches: Sequence[BacktestMatch]) -> LineupIndex:
        return cls({match_key(m.result): m.lineups for m in matches if m.lineups is not None})

    def team_history(self, history: Sequence[MatchResult]) -> dict[str, list[TeamSheet]]:
        """Most recent sheets per team (newest last), from ``history`` only."""
        out: dict[str, list[TeamSheet]] = defaultdict(list)
        for r in sorted(history, key=lambda r: r.kickoff_at):
            lu = self.sheets.get(match_key(r))
            if lu is None:
                continue
            out[r.home].append(lu.home)
            out[r.away].append(lu.away)
        return {team: sheets[-RECENT_MATCHES:] for team, sheets in out.items()}


def strengths_for(
    match: BacktestMatch, recent: Mapping[str, list[TeamSheet]]
) -> tuple[float, float] | None:
    if match.lineups is None:
        return None
    out = []
    for team, sheet in (
        (match.result.home, match.lineups.home),
        (match.result.away, match.lineups.away),
    ):
        sheets = recent.get(team, [])
        out.append(
            1.0
            if len(sheets) < MIN_MATCHES
            else xi_strength(sheet.starters, player_weights(sheets))
        )
    return out[0], out[1]


def adjust(
    lam_h: float, lam_a: float, s_h: float, s_a: float, beta: float, gamma: float
) -> tuple[float, float]:
    return (
        lam_h * math.exp(beta * (s_h - 1) - gamma * (s_a - 1)),
        lam_a * math.exp(beta * (s_a - 1) - gamma * (s_h - 1)),
    )


@dataclass(slots=True)
class LineupForecaster:
    """Production model with expected goals adjusted for line-up strength."""

    name: str
    params: ModelParams
    index: LineupIndex
    beta: float = 0.0
    gamma: float = 0.0
    _model: PoissonEloModel | None = None
    _recent: dict[str, list[TeamSheet]] = field(default_factory=dict)

    def fit(self, history: Sequence[MatchResult], as_of: datetime) -> LineupForecaster:
        self._model = PoissonEloModel(params=replace(self.params)).fit(history, as_of)
        self._recent = self.index.team_history([r for r in history if r.kickoff_at < as_of])
        return self

    def lambdas(self, match: BacktestMatch) -> tuple[float, float]:
        assert self._model is not None
        out = self._model.predict(match.result.home, match.result.away)
        return out.expected_goals_home, out.expected_goals_away

    def predict(self, match: BacktestMatch) -> Probabilities1X2 | None:
        s = strengths_for(match, self._recent)
        if s is None:
            return None
        lam_h, lam_a = adjust(*self.lambdas(match), *s, self.beta, self.gamma)
        p = self.params
        raw = probabilities_from_expected_goals(lam_h, lam_a, p.max_goals, p.dixon_coles_rho)
        if p.draw_inflation != 1.0:
            raw = Probabilities1X2.normalized(raw.home, raw.draw * p.draw_inflation, raw.away)
        return raw


@dataclass(frozen=True, slots=True)
class LineupFit:
    beta: float
    gamma: float
    n_matches: int
    log_likelihood_gain: float  # per match, vs beta = gamma = 0
    mean_strength: float
    share_below_90pct: float


def collect_offsets(
    matches: Sequence[BacktestMatch],
    params: ModelParams,
    start: datetime,
    end: datetime,
    refit_every: timedelta = timedelta(days=7),
    min_history: int = 100,
) -> np.ndarray:
    """Walk-forward rows [lam_h, lam_a, S_h, S_a, goals_h, goals_a] for [start, end)."""
    ordered = sorted(matches, key=lambda m: m.result.kickoff_at)
    index = LineupIndex.build(ordered)
    results = [m.result for m in ordered]
    f = LineupForecaster("_offsets", params, index)
    rows = []
    as_of = start
    while as_of < end:
        window_end = min(as_of + refit_every, end)
        window = [m for m in ordered if as_of <= m.result.kickoff_at < window_end]
        history = [r for r in results if r.kickoff_at < as_of]
        if window and len(history) >= min_history:
            f.fit(history, as_of)
            for m in window:
                s = strengths_for(m, f._recent)
                if s is None:
                    continue
                lam_h, lam_a = f.lambdas(m)
                rows.append([lam_h, lam_a, s[0], s[1], m.result.home_goals, m.result.away_goals])
        as_of = window_end
    return np.asarray(rows, dtype=float).reshape(-1, 6)


def fit_coefficients(rows: np.ndarray) -> LineupFit:
    """Poisson MLE of beta, gamma with the production lambdas as offsets."""
    lam_h, lam_a, s_h, s_a, g_h, g_a = rows.T
    d_h, d_a = s_h - 1, s_a - 1

    def nll(x: np.ndarray) -> float:
        beta, gamma = x
        eta_h = np.log(lam_h) + beta * d_h - gamma * d_a
        eta_a = np.log(lam_a) + beta * d_a - gamma * d_h
        return float(np.sum(np.exp(eta_h) - g_h * eta_h + np.exp(eta_a) - g_a * eta_a))

    res = minimize(nll, x0=np.zeros(2), method="L-BFGS-B", bounds=[(-5, 5), (-5, 5)])
    beta, gamma = (float(v) for v in res.x)
    n = len(rows)
    strengths = np.concatenate([s_h, s_a])
    return LineupFit(
        beta=beta,
        gamma=gamma,
        n_matches=n,
        log_likelihood_gain=(nll(np.zeros(2)) - nll(res.x)) / max(n, 1),
        mean_strength=float(strengths.mean()) if n else 1.0,
        share_below_90pct=float((strengths < 0.9).mean()) if n else 0.0,
    )
