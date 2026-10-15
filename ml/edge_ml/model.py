"""Baseline 1X2 model: Poisson strengths + Elo supremacy -> score matrix.

Pipeline (all steps deterministic, no LLM involvement):

1. Fit Poisson attack/defence strengths on finished matches before ``as_of``.
   -> lambda_home_p, lambda_away_p
2. Replay Elo on the same matches -> rating difference d (incl. home advantage).
3. Blend goal supremacy (home xG - away xG):
       S = w * (lambda_home_p - lambda_away_p) + (1 - w) * d / elo_points_per_goal
   keeping total expected goals T = lambda_home_p + lambda_away_p.
4. lambda_home = (T + S) / 2, lambda_away = (T - S) / 2   (floored at min_lambda)
5. Poisson score matrix -> P(home), P(draw), P(away)
6. Calibrator (identity in the MVP)

Newly promoted teams (v0.2.0): when every match carries a season, a team that
was not in the previous season does not start at league average. Its Elo
starts at, and its attack/defence shrink toward, the mean of the bottom
``newcomer_reference_teams`` established teams at that season's start, i.e.
roughly relegation-level strength. Teams with no match at all (promoted, not
yet played) get the same relegation-level prior.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from edge_ml.calibration import Calibrator, IdentityCalibrator
from edge_ml.core import MatchResult, Probabilities1X2
from edge_ml.elo import EloParams, EloRatings
from edge_ml.poisson import DEFAULT_MAX_GOALS, probabilities_from_expected_goals
from edge_ml.strength import StrengthParams, StrengthRatings, fit_strengths

MODEL_NAME = "poisson-elo-baseline"
MODEL_VERSION = "0.2.0"  # bump on any change that alters outputs
FEATURE_SET = "poisson_strength_v1+elo_supremacy_v1+newcomer_prior_v1"


@dataclass(frozen=True, slots=True)
class ModelParams:
    strength: StrengthParams = field(default_factory=StrengthParams)
    elo: EloParams = field(default_factory=EloParams)
    poisson_weight: float = 0.6
    elo_points_per_goal: float = 280.0
    min_lambda: float = 0.15
    max_goals: int = DEFAULT_MAX_GOALS
    dixon_coles_rho: float = 0.0
    # promoted teams start at the mean of the N weakest established teams
    newcomer_reference_teams: int = 3
    # fraction of each team's Elo distance from the mean removed at a new season
    # (squad turnover); 0 = carry ratings over unchanged (v0.2.0 behaviour)
    elo_season_regression: float = 0.0
    # multiply P(draw) by this factor and renormalise; 1 = unchanged
    draw_inflation: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelOutput:
    probabilities: Probabilities1X2
    raw_probabilities: Probabilities1X2  # before calibration
    expected_goals_home: float
    expected_goals_away: float
    features: dict[str, Any]


@dataclass(slots=True)
class PoissonEloModel:
    params: ModelParams = field(default_factory=ModelParams)
    calibrator: Calibrator = field(default_factory=IdentityCalibrator)
    strengths: StrengthRatings | None = None
    elo: EloRatings | None = None
    as_of: datetime | None = None
    # teams treated as promoted in the latest season (for explainability)
    newcomers: frozenset[str] = frozenset()

    def fit(self, matches: Sequence[MatchResult], as_of: datetime) -> PoissonEloModel:
        """Fit on matches strictly before ``as_of`` (prevents look-ahead bias)."""
        usable = [m for m in matches if m.kickoff_at < as_of]
        seasons = _ordered_seasons(usable)
        self.as_of = as_of
        if len(seasons) < 2:
            # no season information (or a single season): league-average priors
            self.strengths = fit_strengths(usable, as_of, self.params.strength)
            self.elo = EloRatings(params=self.params.elo).fit(usable)
            self.newcomers = frozenset()
            return self

        k = self.params.newcomer_reference_teams
        by_season = {s: [m for m in usable if m.season == s] for s in seasons}
        teams = {s: {t for m in ms for t in (m.home, m.away)} for s, ms in by_season.items()}

        # Elo: replay season by season; newcomers start at relegation level.
        elo = EloRatings(params=self.params.elo)
        r = self.params.elo_season_regression
        for prev, season in zip([None, *seasons], seasons, strict=False):
            if prev is not None and r > 0 and elo.ratings:
                mean = sum(elo.ratings.values()) / len(elo.ratings)
                elo.ratings = {t: mean + (1 - r) * (v - mean) for t, v in elo.ratings.items()}
            if prev is not None:
                prior = _bottom_mean([elo.rating(t) for t in teams[prev]], k)
                for team in teams[season] - teams[prev]:
                    elo.ratings[team] = prior
            elo.fit(by_season[season])
        elo.default_rating = _bottom_mean([elo.rating(t) for t in teams[seasons[-1]]], k)

        # Strengths: newcomers of the latest season shrink toward relegation level.
        latest, previous = seasons[-1], seasons[-2]
        latest_start = min(m.kickoff_at for m in by_season[latest])
        reference = fit_strengths(
            [m for m in usable if m.season != latest], latest_start, self.params.strength
        )
        newcomer_target = _weakest_strength(reference, teams[previous], k)
        newcomers = teams[latest] - teams[previous]
        strengths = fit_strengths(
            usable,
            as_of,
            self.params.strength,
            targets=dict.fromkeys(newcomers, newcomer_target),
        )
        unseen_target = _weakest_strength(strengths, teams[latest], k)
        strengths.default_attack, strengths.default_defence = unseen_target

        self.strengths, self.elo, self.newcomers = strengths, elo, frozenset(newcomers)
        return self

    def _prior_kind(self, team: str) -> str:
        assert self.elo is not None
        if team not in self.elo.ratings:
            return (
                "unseen_relegation_level"
                if self.elo.default_rating is not None
                else "league_average"
            )
        return "promoted_relegation_level" if team in self.newcomers else "data"

    def predict(self, home: str, away: str) -> ModelOutput:
        if self.strengths is None or self.elo is None:
            raise RuntimeError("model must be fitted before predict()")
        p = self.params
        lam_h_p, lam_a_p = self.strengths.expected_goals(home, away)
        total = lam_h_p + lam_a_p
        elo_diff = self.elo.rating_difference(home, away)
        supremacy_poisson = lam_h_p - lam_a_p
        supremacy_elo = elo_diff / p.elo_points_per_goal
        supremacy = p.poisson_weight * supremacy_poisson + (1 - p.poisson_weight) * supremacy_elo

        lam_h = max((total + supremacy) / 2.0, p.min_lambda)
        lam_a = max((total - supremacy) / 2.0, p.min_lambda)

        raw = probabilities_from_expected_goals(lam_h, lam_a, p.max_goals, p.dixon_coles_rho)
        if p.draw_inflation != 1.0:
            raw = Probabilities1X2.normalized(raw.home, raw.draw * p.draw_inflation, raw.away)
        calibrated = self.calibrator.calibrate(raw)
        features: dict[str, Any] = {
            "elo_home": round(self.elo.rating(home), 2),
            "elo_away": round(self.elo.rating(away), 2),
            "elo_diff_incl_hfa": round(elo_diff, 2),
            "attack_home": round(self.strengths.attack.get(home, 1.0), 4),
            "defence_home": round(self.strengths.defence.get(home, 1.0), 4),
            "attack_away": round(self.strengths.attack.get(away, 1.0), 4),
            "defence_away": round(self.strengths.defence.get(away, 1.0), 4),
            "lambda_home_poisson": round(lam_h_p, 4),
            "lambda_away_poisson": round(lam_a_p, 4),
            "supremacy_poisson": round(supremacy_poisson, 4),
            "supremacy_elo": round(supremacy_elo, 4),
            "training_matches": self.strengths.n_matches,
            "matches_home": self.elo.matches_played.get(home, 0),
            "matches_away": self.elo.matches_played.get(away, 0),
            "prior_home": self._prior_kind(home),
            "prior_away": self._prior_kind(away),
            "calibrator": self.calibrator.name,
        }
        return ModelOutput(
            probabilities=calibrated,
            raw_probabilities=raw,
            expected_goals_home=lam_h,
            expected_goals_away=lam_a,
            features=features,
        )


def _ordered_seasons(matches: Sequence[MatchResult]) -> list[str]:
    """Seasons ordered by first kickoff; empty if any match lacks a season."""
    if not matches or any(m.season is None for m in matches):
        return []
    first: dict[str, datetime] = {}
    for m in matches:
        assert m.season is not None
        if m.season not in first or m.kickoff_at < first[m.season]:
            first[m.season] = m.kickoff_at
    return sorted(first, key=first.__getitem__)


def _bottom_mean(values: Sequence[float], k: int) -> float:
    ordered = sorted(values)
    chosen = ordered[: max(1, min(k, len(ordered)))]
    return sum(chosen) / len(chosen)


def _weakest_strength(strengths: StrengthRatings, teams: set[str], k: int) -> tuple[float, float]:
    """Mean (attack, defence) of the k weakest teams by attack/defence ratio."""
    rated = [
        (strengths.attack[t], strengths.defence[t])
        for t in teams
        if t in strengths.attack and t in strengths.defence
    ]
    if not rated:
        return (1.0, 1.0)
    rated.sort(key=lambda ad: ad[0] / ad[1])
    chosen = rated[: max(1, min(k, len(rated)))]
    return (
        sum(a for a, _ in chosen) / len(chosen),
        sum(d for _, d in chosen) / len(chosen),
    )
