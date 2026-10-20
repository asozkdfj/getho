"""Collection quality per pick day, without looking at any result.

Did the pipeline run as often as scheduled, was the day decided (and how long
after the publish hour), and what did the decision have to work with: fixtures
with a prediction and with odds of the configured bookmaker, how old those odds
were, player information and the shadow record. Nothing here reads a score,
a hit or a log loss, so it can be checked daily without peeking at outcomes.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import DailyPick, IngestionRun, ShadowForecast
from edge_api.services import queries
from edge_api.services.picks import local_day
from edge_api.services.shadow import market_odds_at
from edge_api.services.team_news_coverage import coverage_on
from edge_ml.shadow import PROTOCOL

TOP_LEAGUES = 10


def _runs(
    session: Session, provider: str, start: datetime, end: datetime, now: datetime
) -> dict[str, Any]:
    rows = session.execute(
        select(IngestionRun.finished_at, IngestionRun.status, IngestionRun.error)
        .where(
            IngestionRun.provider == provider,
            IngestionRun.finished_at >= start,
            IngestionRun.finished_at < end,
        )
        .order_by(IngestionRun.finished_at)
    ).all()
    ok = [r.finished_at for r in rows if r.status == "success"]
    failed = [r for r in rows if r.status != "success"]
    stop = min(end, now)
    edges = [start, *ok, stop] if stop > start else []
    gaps = [(b - a).total_seconds() / 3600 for a, b in pairwise(edges)]
    return {
        "success": len(ok),
        "failed": len(failed),
        "errors": [(r.error or "")[:120] for r in failed[:3]],
        "longest_gap_hours": round(max(gaps), 2) if gaps else None,
    }


def quality_on(
    session: Session, settings: Settings, day: date, *, now: datetime, interval: timedelta
) -> dict[str, Any]:
    provider = settings.data_provider
    zone = ZoneInfo(settings.pick_tz)
    ld = local_day(datetime.combine(day, time(settings.pick_publish_hour), tzinfo=zone), settings)
    runs = _runs(session, provider, ld.start_utc, ld.end_utc, now)
    covered = max(min(ld.end_utc, now) - ld.start_utc, timedelta(0))
    runs["expected"] = int(covered / interval)
    pick = session.scalars(
        select(DailyPick).where(
            DailyPick.provider == provider, DailyPick.pick_date == day, DailyPick.revision == 1
        )
    ).first()
    decided_at = (
        datetime.fromisoformat(pick.evidence["decided_at"])
        if pick is not None and (pick.evidence or {}).get("decided_at")
        else None
    )
    at = decided_at or ld.publish_at
    fixtures = [
        f
        for f in queries.fixtures_between(session, ld.start_utc, ld.end_utc, provider)
        if f.kickoff_at > at
    ]
    ids = [f.id for f in fixtures]
    preds = {
        fid: p
        for fid, p in queries.latest_predictions_by_fixture(session, ids, as_of=at).items()
        if p.created_at <= at
    }
    odds = market_odds_at(session, ids, settings.bookmaker, at)
    ages = sorted((at - o.captured_at).total_seconds() / 3600 for o in odds.values())
    # by league id: different leagues can share a name ("Premier League")
    leagues: dict[int, Counter[str]] = {}
    for f in fixtures:
        c = leagues.setdefault(f.league_id, Counter())
        c["fixtures"] += 1
        c["with_prediction"] += f.id in preds
        c["with_odds"] += f.id in odds
    names = {f.league_id: f.league for f in fixtures}
    top = sorted(leagues.items(), key=lambda kv: (-kv[1]["fixtures"], kv[0]))[:TOP_LEAGUES]
    shadow = dict(
        session.execute(
            select(ShadowForecast.status, func.count())
            .where(
                ShadowForecast.provider == provider,
                ShadowForecast.decision_date == day,
                ShadowForecast.protocol == PROTOCOL,
            )
            .group_by(ShadowForecast.status)
        ).all()
    )
    player = coverage_on(session, settings, day, at=at)
    return {
        "day": day.isoformat(),
        "runs": runs,
        "decision": {
            "decided": pick is not None,
            "status": pick.status if pick is not None else None,
            "decided_at": decided_at.isoformat() if decided_at else None,
            "minutes_after_publish_hour": round((decided_at - ld.publish_at).total_seconds() / 60)
            if decided_at
            else None,
        },
        "fixtures_at_decision": len(fixtures),
        "with_prediction": len(preds),
        "with_odds": len(odds),
        "odds_age_hours": {
            "median": round(statistics.median(ages), 2) if ages else None,
            "max": round(ages[-1], 2) if ages else None,
            "over_max_age": sum(a > settings.odds_max_age for a in ages),
        },
        "leagues": [
            {
                "league_id": lid,
                "provider_id": names[lid].provider_id,
                "country": names[lid].country,
                "name": names[lid].name,
                **c,
            }
            for lid, c in top
        ],
        "player_info": {k: player[k] for k in ("absences", "lineups_in", "regulars_known")},
        "shadow": {
            "recorded": shadow.get("recorded", 0),
            "excluded": shadow.get("excluded", 0),
            "error": ((pick.evidence or {}).get("shadow") or {}).get("error") if pick else None,
        },
    }


def quality_report(
    session: Session,
    settings: Settings,
    start: date,
    end: date,
    *,
    now: datetime,
    interval: timedelta,
) -> dict[str, Any]:
    days = [
        quality_on(session, settings, start + timedelta(days=i), now=now, interval=interval)
        for i in range((end - start).days + 1)
    ]
    fixtures = sum(d["fixtures_at_decision"] for d in days)
    slots = 2 * fixtures
    known = sum(
        d["player_info"]["absences"]["reported"] + d["player_info"]["absences"]["none_reported"]
        for d in days
    )

    def share(n: int, total: int) -> float | None:
        return round(n / total, 4) if total else None

    return {
        "provider": settings.data_provider,
        "bookmaker": settings.bookmaker,
        "expected_interval_minutes": interval.total_seconds() / 60,
        "note": "outcome-blind: no scores, hits or log loss are read",
        "summary": {
            "days": len(days),
            "days_without_decision": [d["day"] for d in days if not d["decision"]["decided"]],
            "days_with_failed_runs": [d["day"] for d in days if d["runs"]["failed"]],
            "days_with_long_gaps": [
                d["day"]
                for d in days
                if d["runs"]["longest_gap_hours"] is not None
                and d["runs"]["longest_gap_hours"] > 2 * interval.total_seconds() / 3600
            ],
            "days_with_shadow_errors": [d["day"] for d in days if d["shadow"]["error"]],
            "fixtures_at_decision": fixtures,
            "prediction_share": share(sum(d["with_prediction"] for d in days), fixtures),
            "odds_share": share(sum(d["with_odds"] for d in days), fixtures),
            "absences_known_share": share(known, slots),
        },
        "days": days,
    }
