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
from datetime import datetime, time, timedelta
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
    *,
    decision_hour: int | None = None,
    prediction_times: Sequence[datetime] | None = None,
    day_start_hour: int = 0,
) -> list[dict[str, Any]]:
    """Apply the daily rule to walk-forward predictions, for several thresholds.

    ``decision_hour=None`` keeps the historical whole-day replay (every match of
    the local day is a candidate). With a decision hour, as in the service, only
    matches kicking off after that hour, and (when ``prediction_times`` are
    given) predictions available by then, are candidates. ``day_start_hour``
    moves the day boundary: 9 means a "day" runs 09:00 -> 09:00 next day, like
    the service's pick window. Either way this replays timing only, not live
    odds, collection status or quality gates.
    """
    n = len(keys)
    if len(set(keys)) != n:
        raise ValueError("fixture keys must be unique")
    if len(kickoffs) != n or probs.shape != (n, 3) or outcomes.shape != (n,):
        raise ValueError("keys, kickoffs, probabilities and outcomes must align")
    if decision_hour is not None and not 0 <= decision_hour <= 23:
        raise ValueError("decision_hour must be in 0..23")
    if not 0 <= day_start_hour <= 23:
        raise ValueError("day_start_hour must be in 0..23")
    if prediction_times is not None and len(prediction_times) != n:
        raise ValueError("prediction_times must align with keys")
    for stamp in [*kickoffs, *(prediction_times or [])]:
        if stamp.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
    zone = ZoneInfo(tz)
    position = {k: i for i, k in enumerate(keys)}
    days: dict[Any, list[int]] = defaultdict(list)
    shift = timedelta(hours=day_start_hour)
    for i, k in enumerate(kickoffs):
        days[(k.astimezone(zone) - shift).date()].append(i)
    rows = []
    for t in thresholds:
        hits, picked, probs_sum, eligible = 0, 0, 0.0, 0
        for day, idx in days.items():
            if decision_hour is not None:
                decision = datetime.combine(day, time(decision_hour), tzinfo=zone)
                idx = [
                    i
                    for i in idx
                    if kickoffs[i] > decision
                    and (prediction_times is None or prediction_times[i] <= decision)
                ]
            eligible += len(idx)
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
                "decision_hour": decision_hour,
                "day_start_hour": day_start_hour,
                "eligible_matches": eligible,
                "coverage": picked / len(days) if days else None,
                "match_days": len(days),
                "days_with_pick": picked,
                "hits": hits,
                "hit_rate": hits / picked if picked else None,
                "hit_rate_ci": [lo, hi] if picked else None,
                "mean_pick_probability": probs_sum / picked if picked else None,
            }
        )
    return rows
