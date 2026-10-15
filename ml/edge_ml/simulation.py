"""Monte Carlo match simulation from the model's expected goals.

The production model already turns expected goals (lambda) into a full
scoreline distribution. Simulating the match many times draws from exactly that
distribution, so the simulated frequencies converge to the model's
probabilities: a simulation adds no information, it shows the same analysis as
"what happens over many replays" (score lines, goal totals, both teams to
score) plus the sampling noise of a finite number of runs.

Goal times in a single replay are illustrative: each goal is placed uniformly
over 90 minutes, which is what a constant scoring rate implies.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from edge_ml.core import Probabilities1X2
from edge_ml.poisson import probabilities_from_expected_goals, score_matrix

MAX_SHOWN_GOALS = 6  # scores above this are grouped as "6+" in the totals table
TOTAL_LINES = (1.5, 2.5, 3.5)


@dataclass(frozen=True, slots=True)
class ScoreFrequency:
    home: int
    away: int
    share: float  # simulated
    exact: float  # from the model's score matrix


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    runs: int
    seed: int
    lambda_home: float
    lambda_away: float
    outcome_share: Probabilities1X2  # simulated home / draw / away
    outcome_exact: Probabilities1X2  # model probabilities (same distribution)
    standard_error: float  # largest 1 s.e. of the three simulated shares
    top_scores: list[ScoreFrequency]
    total_goals: list[tuple[str, float]]  # ("0", share) ... ("6+", share)
    over: dict[str, float]  # "2.5" -> share of runs with more goals
    both_teams_score: float
    home_clean_sheet: float
    away_clean_sheet: float
    mean_goals: tuple[float, float]


@dataclass(frozen=True, slots=True)
class GoalEvent:
    minute: int
    side: str  # "home" | "away"


@dataclass(frozen=True, slots=True)
class Replay:
    home_goals: int
    away_goals: int
    goals: list[GoalEvent] = field(default_factory=list)


def simulate_match(
    lambda_home: float, lambda_away: float, runs: int = 10_000, seed: int = 0, top: int = 8
) -> SimulationSummary:
    if runs <= 0:
        raise ValueError("runs must be positive")
    rng = np.random.default_rng(seed)
    home = rng.poisson(lambda_home, size=runs)
    away = rng.poisson(lambda_away, size=runs)

    home_win = float(np.mean(home > away))
    draw = float(np.mean(home == away))
    away_win = 1.0 - home_win - draw
    shares = (home_win, draw, away_win)
    standard_error = max(float(np.sqrt(p * (1 - p) / runs)) for p in shares)

    matrix = score_matrix(lambda_home, lambda_away)
    counts = Counter(zip(home.tolist(), away.tolist(), strict=True))
    top_scores = [
        ScoreFrequency(
            home=h,
            away=a,
            share=n / runs,
            exact=float(matrix[h, a]) if h < matrix.shape[0] and a < matrix.shape[1] else 0.0,
        )
        for (h, a), n in counts.most_common(top)
    ]

    totals = home + away
    total_goals = [(str(k), float(np.mean(totals == k))) for k in range(MAX_SHOWN_GOALS)] + [
        (f"{MAX_SHOWN_GOALS}+", float(np.mean(totals >= MAX_SHOWN_GOALS)))
    ]

    return SimulationSummary(
        runs=runs,
        seed=seed,
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        outcome_share=Probabilities1X2(home_win, draw, away_win),
        outcome_exact=probabilities_from_expected_goals(lambda_home, lambda_away),
        standard_error=standard_error,
        top_scores=top_scores,
        total_goals=total_goals,
        over={f"{line:.1f}": float(np.mean(totals > line)) for line in TOTAL_LINES},
        both_teams_score=float(np.mean((home > 0) & (away > 0))),
        home_clean_sheet=float(np.mean(away == 0)),
        away_clean_sheet=float(np.mean(home == 0)),
        mean_goals=(float(home.mean()), float(away.mean())),
    )


def replay_match(lambda_home: float, lambda_away: float, seed: int = 0) -> Replay:
    """One simulated match with goal minutes (illustrative)."""
    rng = np.random.default_rng(seed)
    home, away = int(rng.poisson(lambda_home)), int(rng.poisson(lambda_away))
    minutes = rng.integers(1, 91, size=home + away)
    sides = ["home"] * home + ["away"] * away
    goals = sorted(
        (GoalEvent(int(m), side) for m, side in zip(minutes, sides, strict=True)),
        key=lambda g: (g.minute, g.side),
    )
    return Replay(home, away, goals)
