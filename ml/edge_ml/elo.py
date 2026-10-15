"""Simple Elo rating for long-term team strength.

Elo here is used as a *feature* (rating difference -> goal supremacy), not as
a standalone 1X2 model, because Elo by itself has no notion of a draw.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from edge_ml.core import MatchResult


@dataclass(frozen=True, slots=True)
class EloParams:
    initial_rating: float = 1500.0
    k_factor: float = 20.0
    home_advantage: float = 60.0
    use_goal_difference_multiplier: bool = True


def expected_score(rating_home: float, rating_away: float, home_advantage: float = 0.0) -> float:
    """Expected score (win=1, draw=0.5) for the home side."""
    diff = rating_home + home_advantage - rating_away
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def goal_difference_multiplier(goal_difference: int) -> float:
    """World Football Elo style margin multiplier (1 for draws / 1-goal wins)."""
    gd = abs(goal_difference)
    if gd <= 1:
        return 1.0
    return math.log(gd) + 1.0  # gd>=2 -> 1.69, 2.10, ... grows slowly


@dataclass(slots=True)
class EloRatings:
    params: EloParams = field(default_factory=EloParams)
    ratings: dict[str, float] = field(default_factory=dict)
    matches_played: dict[str, int] = field(default_factory=dict)
    # Rating for teams never seen (e.g. promoted before their first match).
    # None -> params.initial_rating (league average).
    default_rating: float | None = None

    def rating(self, team: str) -> float:
        default = (
            self.default_rating if self.default_rating is not None else self.params.initial_rating
        )
        return self.ratings.get(team, default)

    def update(self, match: MatchResult) -> None:
        r_home, r_away = self.rating(match.home), self.rating(match.away)
        exp_home = expected_score(r_home, r_away, self.params.home_advantage)
        if match.home_goals > match.away_goals:
            actual_home = 1.0
        elif match.home_goals == match.away_goals:
            actual_home = 0.5
        else:
            actual_home = 0.0
        multiplier = (
            goal_difference_multiplier(match.home_goals - match.away_goals)
            if self.params.use_goal_difference_multiplier
            else 1.0
        )
        delta = self.params.k_factor * multiplier * (actual_home - exp_home)
        # zero-sum update: total rating mass is conserved
        self.ratings[match.home] = r_home + delta
        self.ratings[match.away] = r_away - delta
        for team in (match.home, match.away):
            self.matches_played[team] = self.matches_played.get(team, 0) + 1

    def fit(self, matches: Iterable[MatchResult]) -> EloRatings:
        """Replay matches in chronological order (look-ahead safe).

        Ties on kickoff time are broken by team keys so the result does not
        depend on the order rows came back from the database.
        """
        for match in sorted(matches, key=lambda m: (m.kickoff_at, m.home, m.away)):
            self.update(match)
        return self

    def rating_difference(self, home: str, away: str) -> float:
        """Home rating + home advantage - away rating."""
        return self.rating(home) + self.params.home_advantage - self.rating(away)
