"""Shot-based team form: features from shots on target in a team's recent
matches, known only after those matches finished.

For a forecast made at ``cutoff`` a match counts once kickoff + 3 h < cutoff
(the delay the production model uses for results). Per team, the last
``WINDOW`` such league matches with shot data; fewer than ``MIN_MATCHES`` gives
neutral features (zeros). League references come from the last
``LEAGUE_WINDOW`` league matches before the cutoff.

Variants (each a vector per team; the experiment fits own/opponent effects):
  sot        [log((sot_for + 0.5) / (L + 0.5)), log((sot_against + 0.5) / (L + 0.5))]
             L = league shots on target per team-match
  finishing  [(goals_for - k sot_for) / G, (goals_against - k sot_against) / G]
             k = league goals per shot on target, G = league goals per
             team-match: scoring (conceding) above what the shots suggest,
             which the goal-based model takes at face value
  sot_and_finishing  both (4 values)
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

RESULT_DELAY = timedelta(hours=3)
WINDOW = 10
MIN_MATCHES = 5
LEAGUE_WINDOW = 300
VARIANTS = ("sot", "finishing", "sot_and_finishing")


@dataclass(frozen=True, slots=True)
class TeamMatch:
    kickoff_at: datetime
    sot_for: float
    sot_against: float
    goals_for: float
    goals_against: float


class ShotHistory:
    """Shot and goal history of one league's teams."""

    def __init__(self) -> None:
        self._team: dict[str, list[TeamMatch]] = defaultdict(list)
        self._team_times: dict[str, list[datetime]] = {}
        self._league: list[TeamMatch] = []
        self._league_times: list[datetime] = []

    def add(
        self,
        kickoff_at: datetime,
        home: str,
        away: str,
        home_goals: int,
        away_goals: int,
        home_on_target: float,
        away_on_target: float,
    ) -> None:
        h = TeamMatch(kickoff_at, home_on_target, away_on_target, home_goals, away_goals)
        a = TeamMatch(kickoff_at, away_on_target, home_on_target, away_goals, home_goals)
        self._team[home].append(h)
        self._team[away].append(a)
        self._league.extend((h, a))

    def freeze(self) -> ShotHistory:
        for matches in self._team.values():
            matches.sort(key=lambda m: m.kickoff_at)
        self._team_times = {t: [m.kickoff_at for m in ms] for t, ms in self._team.items()}
        self._league.sort(key=lambda m: m.kickoff_at)
        self._league_times = [m.kickoff_at for m in self._league]
        return self

    def _before(self, times: list[datetime], cutoff: datetime) -> int:
        return bisect.bisect_left(times, cutoff - RESULT_DELAY)

    def count(self, team: str, cutoff: datetime) -> int:
        """Matches of ``team`` usable at ``cutoff`` (capped at the window)."""
        return min(self._before(self._team_times.get(team, []), cutoff), WINDOW)

    def features(self, team: str, cutoff: datetime, variant: str) -> np.ndarray:
        size = 4 if variant == "sot_and_finishing" else 2
        n = self._before(self._team_times.get(team, []), cutoff)
        recent = self._team.get(team, [])[max(0, n - WINDOW) : n]
        end = self._before(self._league_times, cutoff)
        league = self._league[max(0, end - 2 * LEAGUE_WINDOW) : end]
        if len(recent) < MIN_MATCHES or len(league) < 2 * MIN_MATCHES:
            return np.zeros(size)
        sot_l = float(np.mean([m.sot_for for m in league]))
        goals_l = float(np.mean([m.goals_for for m in league]))
        k = goals_l / sot_l if sot_l > 0 else 0.0
        sf = float(np.mean([m.sot_for for m in recent]))
        sa = float(np.mean([m.sot_against for m in recent]))
        gf = float(np.mean([m.goals_for for m in recent]))
        ga = float(np.mean([m.goals_against for m in recent]))
        sot = [np.log((sf + 0.5) / (sot_l + 0.5)), np.log((sa + 0.5) / (sot_l + 0.5))]
        finishing = [(gf - k * sf) / (goals_l + 0.1), (ga - k * sa) / (goals_l + 0.1)]
        if variant == "sot":
            return np.array(sot)
        if variant == "finishing":
            return np.array(finishing)
        if variant == "sot_and_finishing":
            return np.array(sot + finishing)
        raise ValueError(f"unknown variant {variant!r}")
