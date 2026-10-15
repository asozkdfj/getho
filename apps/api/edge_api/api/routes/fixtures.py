from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from datetime import date as date_type
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.db.models import Fixture, OddsSnapshot, Prediction
from edge_api.schemas import (
    ErrorOut,
    FixtureDetailOut,
    FixtureListOut,
    FixtureSummaryOut,
    OddsSnapshotOut,
    PredictionOut,
    TeamOut,
)
from edge_api.services import queries
from edge_api.services.analysis import (
    build_prediction_out,
    market_view,
    model_probabilities,
    to_probabilities_out,
)

router = APIRouter(prefix="/fixtures", tags=["fixtures"])


def _summary(
    fixture: Fixture, odds: OddsSnapshot | None, prediction: Prediction | None
) -> FixtureSummaryOut:
    return FixtureSummaryOut(
        id=fixture.id,
        league=fixture.league,
        season=fixture.season,
        round=fixture.round,
        kickoff_at=fixture.kickoff_at,
        status=fixture.status,
        home_team=TeamOut.model_validate(fixture.home_team),
        away_team=TeamOut.model_validate(fixture.away_team),
        home_score=fixture.home_score,
        away_score=fixture.away_score,
        latest_odds=OddsSnapshotOut.model_validate(odds) if odds else None,
        fair_market_probabilities=to_probabilities_out(market_view(odds).fair) if odds else None,
        model_probabilities=(
            to_probabilities_out(model_probabilities(prediction)) if prediction else None
        ),
        prediction_id=prediction.id if prediction else None,
    )


@router.get("", response_model=FixtureListOut, responses={422: {"model": ErrorOut}})
def list_fixtures(
    db: DbSession,
    settings: AppSettings,
    now: Now,
    date: Annotated[
        date_type | None, Query(description="Local date (YYYY-MM-DD) in `tz`. Default: today")
    ] = None,
    days: Annotated[int, Query(ge=1, le=14, description="Number of days from `date`")] = 1,
    tz: Annotated[str, Query(description="IANA timezone used to interpret `date`")] = "UTC",
) -> FixtureListOut:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"unknown timezone: {tz}") from exc
    local_day = date or now.astimezone(zone).date()
    start = datetime.combine(local_day, time.min, tzinfo=zone)
    end = start + timedelta(days=days)

    fixtures = queries.fixtures_between(db, start, end, settings.data_provider)
    ids = [f.id for f in fixtures]
    odds = queries.latest_odds_by_fixture(db, ids, settings.bookmaker)
    preds = queries.latest_predictions_by_fixture(db, ids)
    return FixtureListOut(
        date=local_day.isoformat(),
        days=days,
        tz=tz,
        range_start_utc=start.astimezone(UTC),
        range_end_utc=end.astimezone(UTC),
        fixtures=[_summary(f, odds.get(f.id), preds.get(f.id)) for f in fixtures],
    )


@router.get("/{fixture_id}", response_model=FixtureDetailOut, responses={404: {"model": ErrorOut}})
def get_fixture(fixture_id: int, db: DbSession, settings: AppSettings) -> FixtureDetailOut:
    fixture = queries.get_fixture(db, fixture_id)
    if fixture is None:
        raise HTTPException(status_code=404, detail="fixture not found")
    history = queries.odds_history(db, fixture_id, settings.bookmaker)
    prediction = queries.latest_prediction(db, fixture_id)
    summary = _summary(fixture, history[-1] if history else None, prediction)
    return FixtureDetailOut(
        **summary.model_dump(),
        odds_history=[OddsSnapshotOut.model_validate(o) for o in history],
    )


@router.get(
    "/{fixture_id}/prediction",
    response_model=PredictionOut,
    responses={404: {"model": ErrorOut}},
)
def get_prediction(fixture_id: int, db: DbSession, settings: AppSettings) -> PredictionOut:
    if queries.get_fixture(db, fixture_id) is None:
        raise HTTPException(status_code=404, detail="fixture not found")
    prediction = queries.latest_prediction(db, fixture_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail="no prediction for this fixture yet")
    return build_prediction_out(prediction, settings.value_threshold)
