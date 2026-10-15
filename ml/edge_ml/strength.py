"""Poisson attack/defence strength ratings (Maher-style iterative MLE).

lambda_home(i vs j) = mu_home * attack_i * defence_j
lambda_away(i vs j) = mu_away * attack_j * defence_i

attack > 1 means scores more than average, defence > 1 means concedes more.
A pseudo-count prior shrinks teams with few matches toward 1.0 (league
average), and exponential time decay down-weights old matches.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from edge_ml.core import MatchResult

# Typical EPL goal rates; used when there is no data at all.
DEFAULT_MU_HOME = 1.55
DEFAULT_MU_AWAY = 1.25


@dataclass(frozen=True, slots=True)
class StrengthParams:
    prior_matches: float = 4.0  # shrinkage strength in "matches at league average"
    time_decay_per_day: float = 0.005  # half-life ~ 139 days
    iterations: int = 100
    tolerance: float = 1e-8


@dataclass(slots=True)
class StrengthRatings:
    mu_home: float = DEFAULT_MU_HOME
    mu_away: float = DEFAULT_MU_AWAY
    attack: dict[str, float] = field(default_factory=dict)
    defence: dict[str, float] = field(default_factory=dict)
    n_matches: int = 0
    # used for teams without any match (1.0 = league average)
    default_attack: float = 1.0
    default_defence: float = 1.0

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        att_h = self.attack.get(home, self.default_attack)
        def_h = self.defence.get(home, self.default_defence)
        att_a = self.attack.get(away, self.default_attack)
        def_a = self.defence.get(away, self.default_defence)
        return self.mu_home * att_h * def_a, self.mu_away * att_a * def_h


def fit_strengths(
    matches: Sequence[MatchResult],
    as_of: datetime,
    params: StrengthParams | None = None,
    targets: Mapping[str, tuple[float, float]] | None = None,
) -> StrengthRatings:
    """Fit ratings using only matches that kicked off strictly before ``as_of``.

    ``targets`` maps team -> (attack, defence) the prior shrinks toward; teams not
    listed shrink toward 1.0 (league average). Used for newly promoted teams.
    """
    targets = targets or {}
    params = params or StrengthParams()
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")
    usable = [m for m in matches if m.kickoff_at < as_of]
    if not usable:
        return StrengthRatings()

    # Vectorised (numpy) Maher iterations: walk-forward backtests refit this
    # hundreds of times, so the pure-Python loop was the bottleneck.
    teams = sorted({m.home for m in usable} | {m.away for m in usable})
    index = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    h = np.fromiter((index[m.home] for m in usable), dtype=np.intp, count=len(usable))
    a = np.fromiter((index[m.away] for m in usable), dtype=np.intp, count=len(usable))
    hg = np.fromiter((m.home_goals for m in usable), dtype=float, count=len(usable))
    ag = np.fromiter((m.away_goals for m in usable), dtype=float, count=len(usable))
    age_days = np.fromiter(
        ((as_of - m.kickoff_at).total_seconds() / 86400.0 for m in usable),
        dtype=float,
        count=len(usable),
    )
    w = np.exp(-params.time_decay_per_day * age_days)

    w_total = w.sum()
    # guard against degenerate samples (e.g. only 0-0 draws)
    mu_home = max(float((w * hg).sum() / w_total), 0.2)
    mu_away = max(float((w * ag).sum() / w_total), 0.2)

    # prior expressed as goals at league-average rate
    prior_goals = params.prior_matches * (mu_home + mu_away) / 2.0
    t_att = np.array([targets.get(t, (1.0, 1.0))[0] for t in teams])
    t_def = np.array([targets.get(t, (1.0, 1.0))[1] for t in teams])

    def by_team(idx: np.ndarray, values: np.ndarray) -> np.ndarray:
        return np.bincount(idx, weights=values, minlength=n)

    # goals scored / conceded do not depend on the parameters: compute once
    scored = prior_goals * t_att + by_team(h, w * hg) + by_team(a, w * ag)
    conceded = prior_goals * t_def + by_team(h, w * ag) + by_team(a, w * hg)

    attack = np.ones(n)
    defence = np.ones(n)
    for _ in range(params.iterations):
        exp_scored = (
            prior_goals
            + by_team(h, w * mu_home * defence[a])
            + by_team(a, w * mu_away * defence[h])
        )
        new_attack = scored / exp_scored
        exp_conceded = (
            prior_goals
            + by_team(h, w * mu_away * new_attack[a])
            + by_team(a, w * mu_home * new_attack[h])
        )
        new_defence = conceded / exp_conceded

        # identifiability: geometric mean of attack == 1
        scale = math.exp(float(np.log(new_attack).mean()))
        new_attack = new_attack / scale
        new_defence = new_defence * scale

        delta = max(
            float(np.abs(new_attack - attack).max()), float(np.abs(new_defence - defence).max())
        )
        attack, defence = new_attack, new_defence
        if delta < params.tolerance:
            break

    return StrengthRatings(
        mu_home=mu_home,
        mu_away=mu_away,
        attack={t: float(attack[i]) for t, i in index.items()},
        defence={t: float(defence[i]) for t, i in index.items()},
        n_matches=len(usable),
    )
