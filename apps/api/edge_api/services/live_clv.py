"""Live closing line value: from the 09:00 decision to kickoff, did the market
move toward the production model?

The historical CLV test (`edge backtest-clv`) cannot know when its "early"
prices were captured. Here the decision-time price is exactly what the pick
decision saw: the shadow forecast row stores the production probabilities and
the odds snapshot of the configured bookmaker that was captured and stored by
then. The close is that bookmaker's last 1X2 snapshot captured before the
(current) kickoff time.

Monitoring only, no decision. Prices only: the result of an evaluated fixture is
never read, so looking at this report during the shadow-v1 window does not peek
at its outcomes. (The base rate uses results of fixtures that had finished
before each decision, which the decision could see.)

Statistic: the partial slope of edge_ml.clv, b_model in
    close - early = b_model (model - early) + b_base (base - early),
base = the league's home/draw/away frequencies among fixtures finished before
the decision. Clusters: decision days (as shadow-v1), ISO weeks reported too.
"""

from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from edge_api.db.models import (
    Fixture,
    FixtureObservation,
    FixtureStatus,
    OddsSnapshot,
    ShadowForecast,
)
from edge_ml.clv import partial_slope, plain_slope
from edge_ml.market import devig
from edge_ml.shadow import EVALUATION_START, PROTOCOL

REPORT = "live-clv-v1"
SEED = 20261019
MIN_BASE_MATCHES = 30
FLAG_THRESHOLDS = (0.03, 0.05, 0.10)
FLOAT_TOLERANCE = 1e-9


def _closing(session: Session, books: dict[int, str]) -> dict[int, OddsSnapshot]:
    """Last 1X2 snapshot per fixture from its bookmaker captured before kickoff."""
    out: dict[int, OddsSnapshot] = {}
    by_book: dict[str, list[int]] = defaultdict(list)
    for fid, book in books.items():
        by_book[book].append(fid)
    for book, ids in by_book.items():
        ranked = (
            select(
                OddsSnapshot.id,
                func.row_number()
                .over(
                    partition_by=OddsSnapshot.fixture_id,
                    order_by=(OddsSnapshot.captured_at.desc(), OddsSnapshot.id.desc()),
                )
                .label("rn"),
            )
            .join(Fixture, Fixture.id == OddsSnapshot.fixture_id)
            .where(
                OddsSnapshot.fixture_id.in_(ids),
                OddsSnapshot.bookmaker == book,
                OddsSnapshot.market == "1X2",
                OddsSnapshot.captured_at < Fixture.kickoff_at,
            )
            .subquery()
        )
        for o in session.scalars(
            select(OddsSnapshot)
            .join(ranked, ranked.c.id == OddsSnapshot.id)
            .where(ranked.c.rn == 1)
        ):
            out[o.fixture_id] = o
    return out


class _BaseRates:
    """Home/draw/away frequencies of a league's results as a decision at a given
    time knew them: the latest fixture observation stored by then, finished
    with a score and kicked off at least 3 h before (a later correction or a
    result stored after the decision is not used)."""

    def __init__(self, session: Session, provider: str, league_ids: set[int]) -> None:
        rows = session.execute(
            select(
                Fixture.league_id,
                FixtureObservation.fixture_id,
                FixtureObservation.created_at,
                FixtureObservation.status,
                FixtureObservation.kickoff_at,
                FixtureObservation.home_score,
                FixtureObservation.away_score,
            )
            .join(Fixture, Fixture.id == FixtureObservation.fixture_id)
            .where(Fixture.provider == provider, Fixture.league_id.in_(league_ids))
            .order_by(FixtureObservation.created_at, FixtureObservation.id)
        ).all()
        # league -> fixture -> (stored-at times, states) in storage order
        self.history: dict[int, dict[int, tuple[list[datetime], list[tuple]]]] = defaultdict(dict)
        for league, fixture, stored, *state in rows:
            times, states = self.history[league].setdefault(fixture, ([], []))
            times.append(stored)
            states.append(tuple(state))
        self._cache: dict[tuple[int, datetime], np.ndarray | None] = {}

    def at(self, league: int, before: datetime) -> np.ndarray | None:
        key = (league, before)
        if key not in self._cache:
            counts = np.zeros(3)
            for times, states in self.history[league].values():
                i = bisect.bisect_right(times, before) - 1
                if i < 0:
                    continue
                status, kickoff, hs, as_ = states[i]
                # a result counts once the match is over; kickoff + 3 h is a safe bound
                over = (before - kickoff).total_seconds() >= 3 * 3600
                if status == FixtureStatus.FINISHED.value and None not in (hs, as_) and over:
                    counts[0 if hs > as_ else (1 if hs == as_ else 2)] += 1
            total = counts.sum()
            self._cache[key] = counts / total if total >= MIN_BASE_MATCHES else None
        return self._cache[key]


def _prices(o: OddsSnapshot) -> tuple[float, float, float]:
    return (float(o.odds_home), float(o.odds_draw), float(o.odds_away))


def live_clv_report(
    session: Session,
    provider: str,
    *,
    now: datetime,
    start: date = EVALUATION_START,
    end: date | None = None,
) -> dict[str, Any]:
    end = end or now.date()
    early_snap = aliased(OddsSnapshot)
    rows = session.execute(
        select(ShadowForecast, Fixture, early_snap)
        .join(Fixture, Fixture.id == ShadowForecast.fixture_id)
        .join(early_snap, early_snap.id == ShadowForecast.odds_snapshot_id)
        .where(
            ShadowForecast.provider == provider,
            ShadowForecast.protocol == PROTOCOL,
            ShadowForecast.status == "recorded",
            ShadowForecast.decision_date >= start,
            ShadowForecast.decision_date <= end,
        )
        .order_by(ShadowForecast.decision_date, ShadowForecast.id)
    ).all()
    counts: Counter[str] = Counter(recorded=len(rows))
    playable = []
    for r, f, early in rows:
        if f.status in (FixtureStatus.POSTPONED.value, FixtureStatus.CANCELLED.value):
            counts["not_played"] += 1
        elif f.kickoff_at > now:
            counts["before_kickoff"] += 1
        else:
            playable.append((r, f, early))
    closes = _closing(session, {f.id: early.bookmaker for _, f, early in playable})
    base_rates = _BaseRates(session, provider, {f.league_id for _, f, _ in playable})

    analysed: list[dict[str, Any]] = []
    for r, f, early in playable:
        close = closes.get(f.id)
        if close is None or close.captured_at <= early.captured_at:
            counts["no_later_snapshot"] += 1
            continue
        base = base_rates.at(f.league_id, r.decided_at)
        if base is None:
            counts["no_base_rate"] += 1
            continue
        analysed.append(
            {
                "day": r.decision_date.isoformat(),
                "week": "{}-{:02d}".format(*r.decision_date.isocalendar()[:2]),
                "league": f.league_id,
                "in_scope": r.in_pick_scope,
                "model": r.forecasts["production"],
                "early": r.forecasts["market"],
                "early_raw": _prices(early),
                "close": devig(_prices(close)),
                "base": base.tolist(),
                "lag_minutes": (f.kickoff_at - close.captured_at).total_seconds() / 60,
            }
        )
    counts["analysed"] = len(analysed)
    report: dict[str, Any] = {
        "report": REPORT,
        "source_protocol": PROTOCOL,
        "provider": provider,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": now.isoformat(),
        "note": "prices only: results of the evaluated fixtures are not read; no decision",
        "counts": dict(counts),
        "all": _section(analysed),
        "in_pick_scope": _section([a for a in analysed if a["in_scope"]]),
    }
    report["reading"] = _reading(report["all"])
    return report


def _section(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"n": 0}
    model = np.array([a["model"] for a in items], dtype=float)
    early = np.array([a["early"] for a in items], dtype=float)
    close = np.array([a["close"] for a in items], dtype=float)
    base = np.array([a["base"] for a in items], dtype=float)
    raw = np.array([a["early_raw"] for a in items], dtype=float)
    days = [a["day"] for a in items]
    weeks = [a["week"] for a in items]
    move = close - early
    toward = np.sign(move).ravel() == np.sign(model - early).ravel()
    moved = np.abs(move).ravel() > 1e-6
    flags = []
    for t in FLAG_THRESHOLDS:
        i, k = np.nonzero(model - early >= t - FLOAT_TOLERANCE)
        clv = raw[i, k] * close[i, k] - 1.0
        flags.append(
            {
                "threshold": t,
                "flags": len(clv),
                "mean_clv": float(clv.mean()) if len(clv) else None,
                "share_positive": float((clv > 0).mean()) if len(clv) else None,
            }
        )
    lags = sorted(a["lag_minutes"] for a in items)
    return {
        "n": len(items),
        "days": len(set(days)),
        "mean_abs_move": float(np.abs(move).mean()),
        "share_moves_toward_model": float(toward[moved].mean()) if moved.any() else None,
        "closing_snapshot_minutes_before_kickoff": {
            "median": lags[len(lags) // 2],
            "max": lags[-1],
        },
        "partial_by_day": partial_slope(model, base, early, close, days, SEED),
        "partial_by_week": partial_slope(model, base, early, close, weeks, SEED),
        "plain_model_by_day": plain_slope(model, early, close, days, SEED),
        "plain_base_rate_by_day": plain_slope(base, early, close, days, SEED),
        "large_gap_clv": flags,
    }


def _reading(section: dict[str, Any]) -> dict[str, Any]:
    p = section.get("partial_by_day") or {}
    lower = (p.get("b_forecast_ci95") or [None])[0]
    return {
        "b_model": p.get("b_forecast"),
        "b_model_ci95_by_day": p.get("b_forecast_ci95"),
        "signal": "positive" if lower is not None and lower > 0 else "not_detected",
        "decision": "none (monitoring)",
    }
