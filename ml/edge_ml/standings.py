"""League-table "stakes" features: what a match is worth to each team.

Experiment code. Motivation is not measured directly; these are observable
proxies from the league table built only from results on EARLIER calendar
days (so nothing after kickoff leaks in):

- dead rubber: late in the season a team can neither go down nor reach the
  upper places any more (worst/best case: 3 points per remaining match)
- relegation pressure: how close a team is to the danger zone, weighted by how
  far the season has gone

The thresholds are simple and identical for every league (danger zone = last
3 places, upper line = 6th place); real rules differ by league and season
(play-offs, number of relegated teams), which these proxies ignore.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from edge_ml.core import MatchResult

UK = ZoneInfo("Europe/London")
DANGER_SPOTS = 3
UPPER_LINE = 6
LATE_SEASON_REMAINING = 10  # "dead rubber" is only possible with this many games left
PRESSURE_GAP_POINTS = 9  # pressure fades to 0 at 9 points above the danger zone


@dataclass(frozen=True, slots=True)
class Stakes:
    position: int
    n_teams: int
    played: int
    remaining: int
    points: int
    gap_to_danger: int  # points above the first danger place (<= 0: in the zone)
    gap_to_upper: int  # points behind the upper line (<= 0: on or above it)
    dead: bool
    pressure: float  # 0..1, already weighted by season stage

    @property
    def stage(self) -> float:
        total = self.played + self.remaining
        return self.played / total if total else 0.0


@dataclass(slots=True)
class _Line:
    points: int = 0
    goal_diff: int = 0
    goals_for: int = 0
    played: int = 0


class Standings:
    def __init__(self, results: Sequence[MatchResult], tz: ZoneInfo = UK) -> None:
        self.tz = tz
        self._by_season: dict[str, list[tuple[date, MatchResult]]] = defaultdict(list)
        for r in results:
            self._by_season[r.season or ""].append((r.kickoff_at.astimezone(tz).date(), r))
        for rows in self._by_season.values():
            rows.sort(key=lambda x: (x[0], x[1].kickoff_at))
        self._teams = {
            s: {t for _, r in rows for t in (r.home, r.away)} for s, rows in self._by_season.items()
        }
        self._cache: dict[tuple[str, date], list[tuple[str, _Line]]] = {}

    def table(self, season: str, day: date) -> list[tuple[str, _Line]]:
        """Ranked table from results before ``day`` (points, goal difference, goals)."""
        key = (season, day)
        if key not in self._cache:
            lines = {t: _Line() for t in self._teams.get(season, set())}
            for d, r in self._by_season.get(season, []):
                if d >= day:
                    break
                h, a = lines[r.home], lines[r.away]
                h.played += 1
                a.played += 1
                h.goals_for += r.home_goals
                a.goals_for += r.away_goals
                h.goal_diff += r.home_goals - r.away_goals
                a.goal_diff += r.away_goals - r.home_goals
                if r.home_goals > r.away_goals:
                    h.points += 3
                elif r.home_goals < r.away_goals:
                    a.points += 3
                else:
                    h.points += 1
                    a.points += 1
            self._cache[key] = sorted(
                lines.items(),
                key=lambda kv: (-kv[1].points, -kv[1].goal_diff, -kv[1].goals_for, kv[0]),
            )
        return self._cache[key]

    def stakes(self, team: str, season: str, kickoff_at: datetime) -> Stakes:
        ranked = self.table(season, kickoff_at.astimezone(self.tz).date())
        n = len(ranked)
        total = 2 * (n - 1)
        pos = next(i for i, (t, _) in enumerate(ranked, 1) if t == team)
        me = ranked[pos - 1][1]
        remaining = max(total - me.played, 0)
        danger = ranked[n - DANGER_SPOTS][1]  # first place in the danger zone
        upper = ranked[min(UPPER_LINE, n) - 1][1]
        danger_left = max(total - danger.played, 0)
        safe = pos <= n - DANGER_SPOTS and me.points > danger.points + 3 * danger_left
        out_of_reach = pos > UPPER_LINE and me.points + 3 * remaining < upper.points
        gap_danger = me.points - danger.points
        pressure = min(max(1 - gap_danger / PRESSURE_GAP_POINTS, 0.0), 1.0)
        return Stakes(
            position=pos,
            n_teams=n,
            played=me.played,
            remaining=remaining,
            points=me.points,
            gap_to_danger=gap_danger,
            gap_to_upper=upper.points - me.points,
            dead=remaining <= LATE_SEASON_REMAINING and safe and out_of_reach,
            pressure=pressure * (me.played / total if total else 0.0),
        )


VARIANTS = {
    "dead_rubber": lambda s: [float(s.dead)],
    "relegation_pressure": lambda s: [s.pressure],
    "stakes": lambda s: [float(s.dead), s.pressure],
}
