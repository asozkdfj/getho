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
MODEL_VERSION = "0.1.0"  # bump on any change that alters outputs
FEATURE_SET = "poisson_strength_v1+elo_supremacy_v1"


@dataclass(frozen=True, slots=True)
class ModelParams:
    strength: StrengthParams = field(default_factory=StrengthParams)
    elo: EloParams = field(default_factory=EloParams)
    poisson_weight: float = 0.6
    elo_points_per_goal: float = 280.0
    min_lambda: float = 0.15
    max_goals: int = DEFAULT_MAX_GOALS
    dixon_coles_rho: float = 0.0

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

    def fit(self, matches: Sequence[MatchResult], as_of: datetime) -> PoissonEloModel:
        """Fit on matches strictly before ``as_of`` (prevents look-ahead bias)."""
        usable = [m for m in matches if m.kickoff_at < as_of]
        self.strengths = fit_strengths(usable, as_of, self.params.strength)
        self.elo = EloRatings(params=self.params.elo).fit(usable)
        self.as_of = as_of
        return self

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
            "calibrator": self.calibrator.name,
        }
        return ModelOutput(
            probabilities=calibrated,
            raw_probabilities=raw,
            expected_goals_home=lam_h,
            expected_goals_away=lam_a,
            features=features,
        )
