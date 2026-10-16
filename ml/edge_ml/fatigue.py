"""Fatigue / rest features from a team's schedule in every competition.

Experiment code (the service model does not use it yet). A team's earlier
matches are known before kickoff (dates only, no results), so the features
never look ahead. They are TEAM-level proxies: who actually played those
matches (rotation) is not known from schedules alone.

Adjustment, like the line-up experiment: with fatigue vector x (k values) for
each side,

    log lam_home' = log lam_home + a . x_home - b . x_away
    log lam_away' = log lam_away + a . x_away - b . x_home

a = effect of a team's own fatigue on its scoring, b = effect of the opponent's
fatigue (b > 0: a tired opponent concedes more). a and b are fitted by Poisson
maximum likelihood with the production expected goals as offsets.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from scipy.optimize import minimize

UK = ZoneInfo("Europe/London")
REST_CAP_DAYS = 14  # first match of a season / long breaks count as fully rested
COEF_BOUND = 1.5


@dataclass(frozen=True, slots=True)
class Appearance:
    """One match a team played (any competition)."""

    team: str
    kickoff_at: datetime
    competition: str  # "league", "facup", "eflcup", "cl", "el", "conf"
    extra_time: bool = False


@dataclass(frozen=True, slots=True)
class Fatigue:
    rest_days: int  # calendar days since the previous match (capped)
    load_7: int  # matches in the 7 / 14 / 28 days before the match day
    load_14: int
    load_28: int
    extra_time_4d: bool  # a match that went to extra time in the previous 4 days
    europe_4d: bool  # a European match in the previous 4 days


class Schedule:
    """Per-team match calendar; features use only matches on earlier days."""

    def __init__(self, appearances: Iterable[Appearance], tz: ZoneInfo = UK) -> None:
        self.tz = tz
        by_team: dict[str, list[tuple[date, Appearance]]] = defaultdict(list)
        seen: set[tuple[str, date, str]] = set()
        for a in appearances:
            day = a.kickoff_at.astimezone(tz).date()
            key = (a.team, day, a.competition)
            if key in seen:  # the same match listed twice (e.g. two sources)
                continue
            seen.add(key)
            by_team[a.team].append((day, a))
        self._days: dict[str, list[date]] = {}
        self._apps: dict[str, list[Appearance]] = {}
        for team, rows in by_team.items():
            rows.sort(key=lambda r: (r[0], r[1].kickoff_at))
            self._days[team] = [d for d, _ in rows]
            self._apps[team] = [a for _, a in rows]

    def features(self, team: str, kickoff_at: datetime) -> Fatigue:
        day = kickoff_at.astimezone(self.tz).date()
        days = self._days.get(team, [])
        apps = self._apps.get(team, [])
        end = bisect.bisect_left(days, day)  # strictly earlier calendar days only

        def load(n: int) -> int:
            return end - bisect.bisect_left(days, day - timedelta(days=n))

        recent = [apps[i] for i in range(bisect.bisect_left(days, day - timedelta(days=4)), end)]
        rest = (day - days[end - 1]).days if end else REST_CAP_DAYS
        return Fatigue(
            rest_days=min(rest, REST_CAP_DAYS),
            load_7=load(7),
            load_14=load(14),
            load_28=load(28),
            extra_time_4d=any(a.extra_time for a in recent),
            europe_4d=any(a.competition in {"cl", "el", "conf"} for a in recent),
        )


# --- feature variants (declared before the experiment was run) -------------


def rest_deficit(f: Fatigue) -> float:
    """0 with 6+ days of rest, 1/3 per missing day (5 days -> 0.33, 3 days -> 1.0)."""
    return max(0, 6 - f.rest_days) / 3


def congestion(f: Fatigue) -> float:
    """Matches in the previous 14 days, centred on 2 and scaled (0 -> -1, 4 -> +1)."""
    return (min(f.load_14, 5) - 2) / 2


VARIANTS: dict[str, Callable[[Fatigue], list[float]]] = {
    "rest": lambda f: [rest_deficit(f)],
    "congestion": lambda f: [congestion(f)],
    "rest_congestion_et": lambda f: [rest_deficit(f), congestion(f), float(f.extra_time_4d)],
}


# --- coefficients -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FatigueFit:
    own: tuple[float, ...]  # a
    opponent: tuple[float, ...]  # b
    n_matches: int
    log_likelihood_gain: float  # per match, vs. no adjustment


def adjust(
    lam_h: np.ndarray,
    lam_a: np.ndarray,
    x_h: np.ndarray,
    x_a: np.ndarray,
    own: Sequence[float],
    opponent: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    a, b = np.asarray(own, dtype=float), np.asarray(opponent, dtype=float)
    return (
        lam_h * np.exp(x_h @ a - x_a @ b),
        lam_a * np.exp(x_a @ a - x_h @ b),
    )


def fit(
    lam_h: np.ndarray,
    lam_a: np.ndarray,
    x_h: np.ndarray,
    x_a: np.ndarray,
    goals_h: np.ndarray,
    goals_a: np.ndarray,
) -> FatigueFit:
    """Poisson MLE of (a, b) with the production expected goals as offsets."""
    k = x_h.shape[1]
    log_h, log_a = np.log(lam_h), np.log(lam_a)

    def nll(theta: np.ndarray) -> float:
        a, b = theta[:k], theta[k:]
        eta_h = log_h + x_h @ a - x_a @ b
        eta_a = log_a + x_a @ a - x_h @ b
        return float(np.sum(np.exp(eta_h) - goals_h * eta_h + np.exp(eta_a) - goals_a * eta_a))

    zero = np.zeros(2 * k)
    res = minimize(nll, x0=zero, method="L-BFGS-B", bounds=[(-COEF_BOUND, COEF_BOUND)] * (2 * k))
    n = len(lam_h)
    return FatigueFit(
        own=tuple(float(v) for v in res.x[:k]),
        opponent=tuple(float(v) for v in res.x[k:]),
        n_matches=n,
        log_likelihood_gain=(nll(zero) - nll(res.x)) / max(n, 1),
    )
