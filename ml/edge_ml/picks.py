"""Today's Pick selection - one rule shared by the backtest and the live service.

Given the day's candidate matches (already filtered for status, kickoff and data
quality), pick the single 1X2 outcome with the highest (calibrated) model
probability, provided it reaches ``min_probability``. No candidate -> no pick:
the rule never lowers its bar to fill a day.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from edge_ml.core import Outcome, Probabilities1X2
from edge_ml.metrics import wilson_interval


@dataclass(frozen=True, slots=True)
class PickCandidate:
    key: str  # fixture identifier
    kickoff_at: datetime
    probabilities: Probabilities1X2


@dataclass(frozen=True, slots=True)
class PickChoice:
    candidate: PickCandidate
    outcome: Outcome
    probability: float


def best_outcome(p: Probabilities1X2) -> tuple[Outcome, float]:
    # deterministic tie-break: HOME > AWAY > DRAW when probabilities are equal
    order = [(p.home, 2, Outcome.HOME), (p.away, 1, Outcome.AWAY), (p.draw, 0, Outcome.DRAW)]
    prob, _, outcome = max(order)
    return outcome, prob


def select_pick(candidates: Sequence[PickCandidate], min_probability: float) -> PickChoice | None:
    best: PickChoice | None = None
    for c in candidates:
        outcome, prob = best_outcome(c.probabilities)
        if prob < min_probability:
            continue
        choice = PickChoice(c, outcome, prob)
        if best is None or (prob, -c.kickoff_at.timestamp(), c.key) > (
            best.probability,
            -best.candidate.kickoff_at.timestamp(),
            best.candidate.key,
        ):
            best = choice
    return best


def backtest_daily_picks(
    keys: Sequence[str],
    kickoffs: Sequence[datetime],
    probs: np.ndarray,
    outcomes: np.ndarray,
    thresholds: Sequence[float],
    tz: str = "Asia/Seoul",
) -> list[dict[str, Any]]:
    """Apply the daily rule to walk-forward predictions, for several thresholds."""
    zone = ZoneInfo(tz)
    position = {k: i for i, k in enumerate(keys)}
    days: dict[Any, list[int]] = defaultdict(list)
    for i, k in enumerate(kickoffs):
        days[k.astimezone(zone).date()].append(i)
    rows = []
    for t in thresholds:
        hits, picked, probs_sum = 0, 0, 0.0
        for idx in days.values():
            cands = [
                PickCandidate(keys[i], kickoffs[i], Probabilities1X2.normalized(*probs[i]))
                for i in idx
            ]
            choice = select_pick(cands, t)
            if choice is None:
                continue
            i = position[choice.candidate.key]
            picked += 1
            probs_sum += choice.probability
            hits += int(list(Outcome).index(choice.outcome) == outcomes[i])
        lo, hi = wilson_interval(hits, picked)
        rows.append(
            {
                "min_probability": t,
                "match_days": len(days),
                "days_with_pick": picked,
                "hits": hits,
                "hit_rate": hits / picked if picked else None,
                "hit_rate_ci": [lo, hi] if picked else None,
                "mean_pick_probability": probs_sum / picked if picked else None,
            }
        )
    return rows
