from __future__ import annotations

from datetime import UTC, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.api.routes.fixtures import fixture_summary
from edge_api.schemas import HighlightListOut
from edge_api.services import queries
from edge_api.services.highlights import build_highlights
from edge_api.services.leagues import verified_league_ids

router = APIRouter(prefix="/highlights", tags=["highlights"])


@router.get("", response_model=HighlightListOut)
def list_highlights(
    db: DbSession,
    settings: AppSettings,
    now: Now,
    days: Annotated[int, Query(ge=1, le=14, description="Look-ahead window in days")] = 7,
    limit: Annotated[int, Query(ge=1, le=10)] = 3,
    min_edge: Annotated[float, Query(ge=0.0, le=0.5)] = 0.03,
    league_id: Annotated[int | None, Query(description="Only this league")] = None,
) -> HighlightListOut:
    """Upcoming matches where model and market disagree most (reference only, not advice)."""
    start, end = now.astimezone(UTC), now.astimezone(UTC) + timedelta(days=days)
    fixtures = queries.fixtures_between(db, start, end, settings.data_provider, league_id=league_id)
    preds = queries.latest_predictions_by_fixture(db, [f.id for f in fixtures])
    fixtures = [f for f in fixtures if f.id in preds]  # only predicted matches can qualify
    odds = queries.latest_odds_by_fixture(db, [f.id for f in fixtures], settings.bookmaker)
    verified = verified_league_ids(db, settings.data_provider)
    summaries = {
        f.id: fixture_summary(f, odds.get(f.id), preds.get(f.id), verified) for f in fixtures
    }
    items = build_highlights(
        fixtures,
        preds,
        summaries,
        verified=verified,
        now=now,
        min_edge=min_edge,
        threshold=settings.value_threshold,
        limit=limit,
    )
    return HighlightListOut(
        range_start_utc=start, range_end_utc=end, min_edge=min_edge, items=items
    )
