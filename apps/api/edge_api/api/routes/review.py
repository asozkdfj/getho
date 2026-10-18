"""Review a past day: pre-kickoff predictions next to the results."""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.schemas import (
    ErrorOut,
    ReviewItemOut,
    ReviewOut,
    ReviewPickOut,
    ReviewSummaryOut,
    TeamOut,
)
from edge_api.services.analysis import to_probabilities_out
from edge_api.services.leagues import league_ref
from edge_api.services.review import pick_result, review_day, tier_of

router = APIRouter(prefix="/review", tags=["review"])


@router.get("", response_model=ReviewOut, responses={422: {"model": ErrorOut}})
def review(
    db: DbSession,
    settings: AppSettings,
    now: Now,
    date: Annotated[
        date_type | None, Query(description="Local date (YYYY-MM-DD) in `tz`. Default: yesterday")
    ] = None,
    tz: Annotated[str, Query(description="IANA timezone; default: the pick timezone")] = "",
) -> ReviewOut:
    tz = tz or settings.pick_tz
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"unknown timezone: {tz}") from exc
    day = date or (now.astimezone(zone).date() - timedelta(days=1))
    data = review_day(db, settings, day, tz)
    items = []
    for i in data.items:
        f, top, mtop = i.fixture, i.top, i.market_top
        items.append(
            ReviewItemOut(
                fixture_id=f.id,
                league=league_ref(f.league, data.verified),
                kickoff_at=f.kickoff_at,
                status=f.status,
                home_team=TeamOut.model_validate(f.home_team),
                away_team=TeamOut.model_validate(f.away_team),
                home_score=f.home_score,
                away_score=f.away_score,
                prediction_id=i.prediction.id if i.prediction else None,
                model_probabilities=to_probabilities_out(i.model) if i.model else None,
                market_probabilities=to_probabilities_out(i.market) if i.market else None,
                top_outcome=top[0] if top else None,
                top_probability=top[1] if top else None,
                tier=tier_of(top[1]) if top else None,  # type: ignore[arg-type]
                market_top_outcome=mtop[0] if mtop else None,
                actual_outcome=i.actual,
                hit=i.hit,
                market_hit=i.market_hit,
            )
        )
    return ReviewOut(
        date=day.isoformat(),
        tz=tz,
        is_demo=data.demo,
        range_start_utc=data.start_utc,
        range_end_utc=data.end_utc,
        summary=ReviewSummaryOut(**data.summaries["verified"]),
        summary_all=ReviewSummaryOut(**data.summaries["all"]),
        pick=ReviewPickOut(**pick_result(data.pick)) if data.pick else None,
        items=items,
    )
