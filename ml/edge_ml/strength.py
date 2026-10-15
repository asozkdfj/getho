"""Poisson attack/defence strength ratings (Maher-style iterative MLE).

lambda_home(i vs j) = mu_home * attack_i * defence_j
lambda_away(i vs j) = mu_away * attack_j * defence_i

attack > 1 means scores more than average, defence > 1 means concedes more.
A pseudo-count prior shrinks teams with few matches toward 1.0 (league
average), and exponential time decay down-weights old matches.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

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

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        att_h, def_h = self.attack.get(home, 1.0), self.defence.get(home, 1.0)
        att_a, def_a = self.attack.get(away, 1.0), self.defence.get(away, 1.0)
        return self.mu_home * att_h * def_a, self.mu_away * att_a * def_h


def fit_strengths(
    matches: Sequence[MatchResult],
    as_of: datetime,
    params: StrengthParams | None = None,
) -> StrengthRatings:
    """Fit ratings using only matches that kicked off strictly before ``as_of``."""
    params = params or StrengthParams()
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")
    usable = [m for m in matches if m.kickoff_at < as_of]
    if not usable:
        return StrengthRatings()

    weights = [
        math.exp(-params.time_decay_per_day * (as_of - m.kickoff_at).total_seconds() / 86400.0)
        for m in usable
    ]
    w_total = sum(weights)
    mu_home = sum(w * m.home_goals for w, m in zip(weights, usable, strict=True)) / w_total
    mu_away = sum(w * m.away_goals for w, m in zip(weights, usable, strict=True)) / w_total
    # guard against degenerate samples (e.g. only 0-0 draws)
    mu_home = max(mu_home, 0.2)
    mu_away = max(mu_away, 0.2)

    teams = sorted({m.home for m in usable} | {m.away for m in usable})
    attack = dict.fromkeys(teams, 1.0)
    defence = dict.fromkeys(teams, 1.0)
    # prior expressed as goals at league-average rate
    prior_goals = params.prior_matches * (mu_home + mu_away) / 2.0

    for _ in range(params.iterations):
        scored = dict.fromkeys(teams, prior_goals)
        exp_scored = dict.fromkeys(teams, prior_goals)
        conceded = dict.fromkeys(teams, prior_goals)
        exp_conceded = dict.fromkeys(teams, prior_goals)
        for w, m in zip(weights, usable, strict=True):
            scored[m.home] += w * m.home_goals
            scored[m.away] += w * m.away_goals
            exp_scored[m.home] += w * mu_home * defence[m.away]
            exp_scored[m.away] += w * mu_away * defence[m.home]
        new_attack = {t: scored[t] / exp_scored[t] for t in teams}
        for w, m in zip(weights, usable, strict=True):
            conceded[m.home] += w * m.away_goals
            conceded[m.away] += w * m.home_goals
            exp_conceded[m.home] += w * mu_away * new_attack[m.away]
            exp_conceded[m.away] += w * mu_home * new_attack[m.home]
        new_defence = {t: conceded[t] / exp_conceded[t] for t in teams}

        # identifiability: geometric mean of attack == 1
        log_mean = sum(math.log(v) for v in new_attack.values()) / len(teams)
        scale = math.exp(log_mean)
        new_attack = {t: v / scale for t, v in new_attack.items()}
        new_defence = {t: v * scale for t, v in new_defence.items()}

        delta = max(
            max(abs(new_attack[t] - attack[t]) for t in teams),
            max(abs(new_defence[t] - defence[t]) for t in teams),
        )
        attack, defence = new_attack, new_defence
        if delta < params.tolerance:
            break

    return StrengthRatings(
        mu_home=mu_home, mu_away=mu_away, attack=attack, defence=defence, n_matches=len(usable)
    )
