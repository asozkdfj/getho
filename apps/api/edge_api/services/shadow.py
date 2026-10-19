"""Shadow forecasts: at the moment a day's pick is decided, record what the
production model, the market alone and the fixed blend said about every
fixture in the pick window (docs/experiments/shadow-forecasts-2026.md).

Nothing here is shown in the product or changes the pick. The rows are
append-only and use exactly the inputs the decision could see: the same
predictions (``as_of`` the decision time) and the latest odds of the
configured bookmaker that were captured and stored by then.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import Fixture, FixtureStatus, OddsSnapshot, Prediction, ShadowForecast
from edge_api.versioning import build_info
from edge_ml.metrics import cluster_bootstrap_ci
from edge_ml.shadow import (
    CI_SEED,
    DESCRIPTIVE,
    EVALUATION_END,
    EVALUATION_START,
    MIN_GAIN,
    MIN_SETTLED,
    PRIMARY,
    PROTOCOL,
    candidates,
)


def market_odds_at(
    session: Session, fixture_ids: list[int], bookmaker: str, at: datetime
) -> dict[int, OddsSnapshot]:
    """Latest 1X2 snapshot per fixture from ``bookmaker`` that was both captured
    and stored by ``at`` (a later row cannot have been seen at the decision)."""
    if not fixture_ids:
        return {}
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
        .where(
            OddsSnapshot.fixture_id.in_(fixture_ids),
            OddsSnapshot.bookmaker == bookmaker,
            OddsSnapshot.market == "1X2",
            OddsSnapshot.captured_at <= at,
            OddsSnapshot.created_at <= at,
        )
        .subquery()
    )
    rows = session.scalars(
        select(OddsSnapshot).join(ranked, ranked.c.id == OddsSnapshot.id).where(ranked.c.rn == 1)
    ).all()
    return {o.fixture_id: o for o in rows}


def _exclusion(
    f: Fixture,
    p: Prediction | None,
    odds: OddsSnapshot | None,
    at: datetime,
    max_odds_age: timedelta,
) -> str | None:
    if f.status != FixtureStatus.SCHEDULED.value or f.kickoff_at <= at:
        return "not_upcoming"
    if p is None:
        return "no_prediction"
    if p.created_at > at or p.input_data_as_of > at:
        return "prediction_after_decision"
    if odds is None:
        return "no_market_odds"
    if at - odds.captured_at > max_odds_age:
        return "stale_market_odds"
    prices = (float(odds.odds_home), float(odds.odds_draw), float(odds.odds_away))
    if not all(math.isfinite(o) and o > 1.0 for o in prices):
        return "invalid_market_odds"
    return None


def record_shadow_forecasts(
    session: Session,
    settings: Settings,
    *,
    decision_date: date,
    decided_at: datetime,
    fixtures: list[Fixture],
    in_scope: set[int],
    predictions: dict[int, Prediction],
) -> dict[str, int]:
    """One row per fixture of the window; idempotent per (day, protocol)."""
    odds = market_odds_at(session, [f.id for f in fixtures], settings.bookmaker, decided_at)
    build = build_info()
    max_age = timedelta(hours=settings.odds_max_age)
    counts: Counter[str] = Counter()
    for f in fixtures:
        p, o = predictions.get(f.id), odds.get(f.id)
        reason = _exclusion(f, p, o, decided_at, max_age)
        forecasts = None
        if reason is None:
            assert p is not None and o is not None
            forecasts = candidates(
                (p.probability_home, p.probability_draw, p.probability_away),
                (float(o.odds_home), float(o.odds_draw), float(o.odds_away)),
            )
        values: dict[str, Any] = {
            "provider": settings.data_provider,
            "protocol": PROTOCOL,
            "decision_date": decision_date,
            "decided_at": decided_at,
            "fixture_id": f.id,
            "kickoff_at": f.kickoff_at,
            "in_pick_scope": f.id in in_scope,
            "status": "recorded" if reason is None else "excluded",
            "excluded_reason": reason,
            "prediction_id": p.id if p is not None else None,
            "prediction_created_at": p.created_at if p is not None else None,
            "input_data_as_of": p.input_data_as_of if p is not None else None,
            "odds_snapshot_id": o.id if o is not None else None,
            "bookmaker": o.bookmaker if o is not None else None,
            "odds_captured_at": o.captured_at if o is not None else None,
            "odds_stored_at": o.created_at if o is not None else None,
            "forecasts": forecasts,
            "build": build,
        }
        inserted = session.execute(
            insert(ShadowForecast)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_shadow_forecasts_one_per_day")
            .returning(ShadowForecast.id)
        ).scalar_one_or_none()
        counts["recorded" if reason is None else "excluded"] += inserted is not None
    return dict(counts)


def _outcome(f: Fixture) -> int | None:
    """Index into (home, draw, away), or None if the match has no result."""
    if f.status != FixtureStatus.FINISHED.value or f.home_score is None or f.away_score is None:
        return None
    if f.home_score > f.away_score:
        return 0
    return 1 if f.home_score == f.away_score else 2


def shadow_report(
    session: Session,
    provider: str,
    *,
    now: datetime,
    start: date = EVALUATION_START,
    end: date = EVALUATION_END,
) -> dict[str, Any]:
    """Compare the candidates on settled recorded fixtures of decision days
    ``start``..``end``. Only the pre-registered window, complete and with
    enough matches, gives a ``final`` result; anything else is descriptive."""
    rows = session.execute(
        select(ShadowForecast, Fixture)
        .join(Fixture, Fixture.id == ShadowForecast.fixture_id)
        .where(
            ShadowForecast.provider == provider,
            ShadowForecast.protocol == PROTOCOL,
            ShadowForecast.decision_date >= start,
            ShadowForecast.decision_date <= end,
        )
        .order_by(ShadowForecast.decision_date, ShadowForecast.id)
    ).all()
    excluded = Counter(r.excluded_reason for r, _ in rows if r.status == "excluded")
    settled, pending, not_played = [], 0, 0
    for r, f in rows:
        if r.status != "recorded":
            continue
        y = _outcome(f)
        if y is not None:
            settled.append((r, y))
        elif f.status in (FixtureStatus.POSTPONED.value, FixtureStatus.CANCELLED.value):
            not_played += 1
        else:
            pending += 1

    names = [*PRIMARY, *DESCRIPTIVE]
    metrics = _metrics(settled, names)
    report: dict[str, Any] = {
        "protocol": PROTOCOL,
        "provider": provider,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": len(rows),
        "recorded": sum(1 for r, _ in rows if r.status == "recorded"),
        "excluded": dict(sorted(excluded.items())),
        "settled": len(settled),
        "pending": pending,
        "not_played": not_played,
        "metrics": metrics,
        "in_pick_scope": _metrics([(r, y) for r, y in settled if r.in_pick_scope], names),
    }
    pre_registered = (start, end) == (EVALUATION_START, EVALUATION_END)
    complete = pending == 0 and now.date() > end
    if not (pre_registered and complete):
        report["status"] = "provisional"  # descriptive only; never a decision
    elif len(settled) < MIN_SETTLED:
        report["status"] = "inconclusive"
    else:
        report["status"] = "final"
    # the pre-registered questions are answered only by a final report
    report["decisions"] = _decisions(metrics) if report["status"] == "final" else {}
    report["decision_timing"] = _decision_timing(rows)
    report["coverage_days"] = _coverage_days(session, provider, start, min(end, now.date()), rows)
    return report


def _decision_timing(rows: list[Any]) -> dict[str, Any]:
    """How long after the publish hour each day was actually decided (the first
    request or pipeline run after it): shadow-v1 compares candidates at that
    moment, which is not a fixed 09:00 decision."""
    from edge_api.config import get_settings
    from edge_api.services.picks import local_day

    settings = get_settings()
    delays = sorted(
        {
            r.decision_date: (r.decided_at - local_day(r.decided_at, settings).publish_at)
            for r, _ in rows
        }.values()
    )
    if not delays:
        return {"days": 0}
    minutes = [d.total_seconds() / 60 for d in delays]
    return {
        "days": len(minutes),
        "minutes_after_publish_hour": {
            "median": minutes[len(minutes) // 2],
            "max": minutes[-1],
        },
        "days_over_60_minutes": sum(m > 60 for m in minutes),
    }


def _coverage_days(
    session: Session, provider: str, start: date, end: date, rows: list[Any]
) -> dict[str, Any]:
    """Days of the window by what was recorded: a missing day is not the same as
    a day whose fixtures were all excluded."""
    from edge_api.db.models import DailyPick

    if end < start:
        return {"days": 0}
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    with_rows = {r.decision_date for r, _ in rows}
    picks = session.execute(
        select(DailyPick.pick_date, DailyPick.evidence).where(
            DailyPick.provider == provider,
            DailyPick.pick_date >= start,
            DailyPick.pick_date <= end,
            DailyPick.revision == 1,
        )
    ).all()
    decided = {d: (ev or {}).get("shadow") for d, ev in picks}
    no_decision = [d for d in days if d not in decided]
    failed = [d for d in days if isinstance(decided.get(d), dict) and "error" in decided[d]]
    empty = [d for d in days if d in decided and d not in with_rows and d not in failed]
    return {
        "days": len(days),
        "with_records": len([d for d in days if d in with_rows]),
        "no_decision": [d.isoformat() for d in no_decision],
        "shadow_failed": [d.isoformat() for d in failed],
        "decided_without_fixtures_or_records": [d.isoformat() for d in empty],
    }


def _metrics(settled: list[tuple[ShadowForecast, int]], names: list[str]) -> dict[str, Any]:
    if not settled:
        return {"n": 0}
    y = np.array([o for _, o in settled])
    days = [r.decision_date.isoformat() for r, _ in settled]
    probs = {name: np.array([r.forecasts[name] for r, _ in settled], dtype=float) for name in names}
    ll = {k: -np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)) for k, p in probs.items()}
    brier = {k: ((p - np.eye(3)[y]) ** 2).sum(axis=1) for k, p in probs.items()}
    out: dict[str, Any] = {"n": len(y), "days": len(set(days))}
    for k in names:
        out[k] = {
            "log_loss": float(ll[k].mean()),
            "brier": float(brier[k].mean()),
            "accuracy": float((probs[k].argmax(axis=1) == y).mean()),
        }

    weeks = [r.decision_date.isocalendar()[:2] for r, _ in settled]

    def paired(a: str, b: str) -> dict[str, Any]:
        diff = ll[a] - ll[b]  # negative: a is better
        lo, hi = cluster_bootstrap_ci(diff, days, seed=CI_SEED)
        # secondary (addendum of 2026-10-19): ISO-week clusters, reported next to
        # the pre-registered day clusters; if they disagree, both are reported
        wlo, whi = cluster_bootstrap_ci(diff, weeks, seed=CI_SEED)
        return {
            "log_loss_diff": float(diff.mean()),
            "ci95_by_day": [lo, hi],
            "ci95_by_week": [wlo, whi],
            "weeks": len(set(weeks)),
            "brier_diff": float((brier[a] - brier[b]).mean()),
        }

    out["paired"] = {
        "market_vs_production": paired("market", "production"),
        "blend_vs_production": paired("blend_w0.25", "production"),
        "blend_vs_market": paired("blend_w0.25", "market"),
        "calibrated_vs_production": paired("production_calibrated_v1", "production"),
    }
    return out


def _decisions(m: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered questions. Only meaningful when status is final."""

    def beats_production(key: str) -> bool:
        d = m["paired"][key]
        return bool(
            -d["log_loss_diff"] >= MIN_GAIN and d["ci95_by_day"][1] < 0 and d["brier_diff"] <= 0
        )

    bm = m["paired"]["blend_vs_market"]
    if bm["ci95_by_day"][1] < 0:
        blend_vs_market = "blend_better"
    elif bm["ci95_by_day"][0] > 0:
        blend_vs_market = "market_better"
    else:
        blend_vs_market = "no_clear_difference"
    return {
        "market_beats_production": beats_production("market_vs_production"),
        "blend_beats_production": beats_production("blend_vs_production"),
        "blend_vs_market": blend_vs_market,
    }
