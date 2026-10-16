"""Goal markets from a score distribution: over/under totals and Asian handicap.

Asian handicap settlement for the side given ``line`` (e.g. home -0.75):
the side's goal difference plus the line decides the bet. Quarter lines
(x.25, x.75) split the stake over the two neighbouring lines, so a bet can be
a full win, half win, push, half loss or full loss. ``settle`` returns the
share of the stake won and lost, ``(won, lost)`` in {0, 0.5, 1}.

For prices, the fair probability of a side is ``A / (A + B)`` where ``A`` is
the expected share won and ``B`` the expected share lost: at odds ``o`` the
expected profit ``A (o - 1) - B`` is zero exactly when ``1 / o = A / (A + B)``.
That is also what a bookmaker's two prices estimate once the margin is
removed, so model and market probabilities are on the same scale.
"""

from __future__ import annotations

import numpy as np


def over_probability(matrix: np.ndarray, line: float = 2.5) -> float:
    """P(total goals > line) from a score matrix M[home, away]."""
    goals = np.arange(matrix.shape[0])
    totals = goals[:, None] + goals[None, :]
    return float(matrix[totals > line].sum())


def _halves(line: float) -> tuple[float, float]:
    quarter = round(line * 4) % 2 != 0  # x.25 / x.75
    return (line - 0.25, line + 0.25) if quarter else (line, line)


def settle(goal_diff: int, line: float) -> tuple[float, float]:
    """(share won, share lost) of a bet on the side whose goal difference is
    ``goal_diff`` at handicap ``line``; the rest of the stake is returned."""
    won = lost = 0.0
    for half in _halves(line):
        margin = goal_diff + half
        if margin > 0:
            won += 0.5
        elif margin < 0:
            lost += 0.5
    return won, lost


def handicap_shares(matrix: np.ndarray, line: float) -> tuple[float, float]:
    """Expected (share won, share lost) of the home side at ``line``."""
    goals = np.arange(matrix.shape[0])
    diff = goals[:, None] - goals[None, :]
    won = lost = 0.0
    for d in np.unique(diff):
        p = float(matrix[diff == d].sum())
        w, lo = settle(int(d), line)
        won += p * w
        lost += p * lo
    return won, lost


def handicap_probability(matrix: np.ndarray, line: float) -> float:
    """Fair probability of the home side at ``line`` (pushes excluded)."""
    won, lost = handicap_shares(matrix, line)
    return won / (won + lost)


def two_way_devig(price_a: float, price_b: float) -> float:
    """Probability of side A with the margin removed proportionally."""
    a, b = 1 / price_a, 1 / price_b
    return a / (a + b)


def profit(won: float, lost: float, price: float) -> float:
    """Profit of a 1-unit bet at ``price`` given the settled shares."""
    return won * (price - 1) - lost
