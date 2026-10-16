from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.api.routes.fixtures import fixture_summary
from edge_api.db.models import DailyPick
from edge_api.schemas import (
    ErrorOut,
    ExpectedGoalsOut,
    ModelVersionOut,
    PickBacktestOut,
    PickCandidateOut,
    PickHistoryItemOut,
    PickHistoryOut,
    PickHistorySummaryOut,
    PickResultOut,
    ProbabilitiesOut,
    QualityCheckOut,
    TodayPickOut,
)
from edge_api.services import queries
from edge_api.services.leagues import verified_league_ids
from edge_api.services.picks import (
    effective_status,
    get_today_pick,
    pick_history,
    recorded_before_kickoff,
)

router = APIRouter(prefix="/picks", tags=["picks"])


def _result(pick: DailyPick) -> PickResultOut | None:
    for e in reversed(pick.events):
        return PickResultOut(
            event=e.event,
            actual_outcome=e.actual_outcome,
            hit=e.hit,
            reason=e.reason,
            recorded_at=e.created_at,
        )
    return None


@router.get("/today", response_model=TodayPickOut, responses={422: {"model": ErrorOut}})
def today(
    db: DbSession,
    settings: AppSettings,
    now: Now,
    tz: Annotated[str, Query(description="Only the configured pick timezone is supported")] = "",
) -> TodayPickOut:
    """The pick day's single highest-probability outcome that passed the quality gate.

    A pick day runs from the publish hour to the same hour the next day (pick_tz)."""
    if tz and tz != settings.pick_tz:
        raise HTTPException(422, f"picks are published for {settings.pick_tz} days only")
    view = get_today_pick(db, settings, now)
    base: dict[str, Any] = {
        "date": view.day.day.isoformat(),
        "tz": view.day.tz,
        "status": view.status,
        "is_demo": settings.data_provider == "mock",
        "publish_at": view.day.publish_at,
        "window_start": view.day.start_utc,
        "window_end": view.day.end_utc,
        "threshold": settings.pick_min_probability,
    }
    pick = view.pick
    if pick is None:
        return TodayPickOut(**base)
    ev = pick.evidence or {}
    base.update(
        threshold=ev.get("threshold", settings.pick_min_probability),
        pick_id=pick.id,
        revision=pick.revision,
        published_at=pick.published_at,
        factors_used=ev.get("factors_used", []),
        candidates=[PickCandidateOut(**c) for c in ev.get("candidates", [])],
        league_scope=ev.get("league_scope", "verified"),
        matches_today=ev.get("matches_today"),
        matches_in_scope=ev.get("matches_in_scope", ev.get("matches_today")),
        backtest=PickBacktestOut(**ev["backtest"]) if ev.get("backtest") else None,
        result=_result(pick),
    )
    chosen = ev.get("chosen")
    if pick.fixture is not None and pick.prediction is not None and chosen:
        odds = queries.latest_odds_by_fixture(db, [pick.fixture.id], settings.bookmaker)
        base.update(
            fixture=fixture_summary(
                pick.fixture,
                odds.get(pick.fixture.id),
                pick.prediction,
                verified_league_ids(db, settings.data_provider),
            ),
            outcome=pick.outcome,
            probability=pick.probability,
            probabilities=ProbabilitiesOut(**chosen["probabilities"]),
            expected_goals=ExpectedGoalsOut(**chosen["expected_goals"]),
            model=ModelVersionOut.model_validate(pick.prediction.model_version),
            prediction_id=pick.prediction_id,
            input_data_as_of=pick.input_data_as_of,
            features=chosen.get("features", {}),
            quality_checks=[QualityCheckOut(**c) for c in chosen.get("quality_checks", [])],
        )
    return TodayPickOut(**base)


@router.get("/history", response_model=PickHistoryOut)
def history(
    db: DbSession,
    settings: AppSettings,
    limit: Annotated[int, Query(ge=1, le=365)] = 60,
) -> PickHistoryOut:
    data = pick_history(db, settings, limit)
    items = []
    for p in data["picks"]:
        result = _result(p)
        f = p.fixture
        items.append(
            PickHistoryItemOut(
                pick_id=p.id,
                date=p.pick_date.isoformat(),
                revision=p.revision,
                status=effective_status(p),
                fixture_id=p.fixture_id,
                home=f.home_team.name if f else None,
                away=f.away_team.name if f else None,
                kickoff_at=f.kickoff_at if f else None,
                outcome=p.outcome,
                probability=p.probability,
                model_version=(p.evidence or {}).get("model", {}).get("version"),
                actual_outcome=result.actual_outcome if result else None,
                hit=result.hit if result else None,
                reason=result.reason if result else None,
                published_at=p.published_at,
                recorded_before_kickoff=recorded_before_kickoff(p),
            )
        )
    return PickHistoryOut(
        is_demo=settings.data_provider == "mock",
        items=items,
        summary=PickHistorySummaryOut(**data["summary"]),
    )
