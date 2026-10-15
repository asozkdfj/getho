"""Independent Poisson score model: expected goals -> score matrix -> 1X2."""

from __future__ import annotations

import numpy as np
from scipy.stats import poisson

from edge_ml.core import Probabilities1X2

DEFAULT_MAX_GOALS = 10


def score_matrix(
    lambda_home: float,
    lambda_away: float,
    max_goals: int = DEFAULT_MAX_GOALS,
    rho: float = 0.0,
) -> np.ndarray:
    """Return an (n+1)x(n+1) matrix M where M[i, j] = P(home=i, away=j).

    The tail beyond ``max_goals`` is truncated and the matrix is renormalised so
    it sums to exactly 1. ``rho`` applies the Dixon-Coles low-score correction
    (rho=0 -> plain independent Poisson, which is the MVP default).
    """
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError("expected goals must be positive")
    if max_goals < 1:
        raise ValueError("max_goals must be >= 1")

    goals = np.arange(max_goals + 1)
    home_pmf = poisson.pmf(goals, lambda_home)
    away_pmf = poisson.pmf(goals, lambda_away)
    matrix = np.outer(home_pmf, away_pmf)

    if rho != 0.0:
        matrix = _apply_dixon_coles(matrix, lambda_home, lambda_away, rho)

    total = matrix.sum()
    if total <= 0:
        raise ValueError("degenerate score matrix")
    return matrix / total


def _apply_dixon_coles(
    matrix: np.ndarray, lambda_home: float, lambda_away: float, rho: float
) -> np.ndarray:
    adjusted = matrix.copy()
    adjusted[0, 0] *= 1 - lambda_home * lambda_away * rho
    adjusted[0, 1] *= 1 + lambda_home * rho
    adjusted[1, 0] *= 1 + lambda_away * rho
    adjusted[1, 1] *= 1 - rho
    if (adjusted < 0).any():
        raise ValueError("rho too large for the given expected goals")
    return adjusted


def outcome_probabilities(matrix: np.ndarray) -> Probabilities1X2:
    """Collapse a score matrix into home win / draw / away win probabilities."""
    home = float(np.tril(matrix, k=-1).sum())  # i > j
    draw = float(np.trace(matrix))
    away = float(np.triu(matrix, k=1).sum())  # j > i
    return Probabilities1X2.normalized(home, draw, away)


def probabilities_from_expected_goals(
    lambda_home: float, lambda_away: float, max_goals: int = DEFAULT_MAX_GOALS, rho: float = 0.0
) -> Probabilities1X2:
    return outcome_probabilities(score_matrix(lambda_home, lambda_away, max_goals, rho))
