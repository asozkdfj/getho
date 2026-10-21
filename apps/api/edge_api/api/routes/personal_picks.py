from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.schemas import (
    ErrorOut,
    PersonalPickDetailOut,
    PersonalPickIn,
    PersonalPickListOut,
    PersonalPickRevisionIn,
)
from edge_api.services import personal_picks
from edge_api.services.personal_picks import PickConflictError, PickError, PickNotFoundError

router = APIRouter(prefix="/personal-picks", tags=["personal-picks"])

ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorOut},
    409: {"model": ErrorOut},
    422: {"model": ErrorOut},
}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PickNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PickConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.post("", response_model=PersonalPickDetailOut, responses=ERRORS)
def create_pick(
    request: PersonalPickIn, db: DbSession, settings: AppSettings, now: Now
) -> PersonalPickDetailOut:
    """Record your own 1X2 pick. The pre-match analysis is frozen from what was
    known at the decision time; resending the same ``idempotency_key`` returns the
    stored pick without storing a second one."""
    try:
        return personal_picks.create_pick(
            db, request, now=now, bookmaker=settings.bookmaker, provider=settings.data_provider
        )
    except (PickError, PickNotFoundError, PickConflictError) as exc:
        raise _http(exc) from exc


@router.get("", response_model=PersonalPickListOut)
def list_picks(
    db: DbSession,
    settings: AppSettings,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> PersonalPickListOut:
    return personal_picks.list_picks(db, provider=settings.data_provider, limit=limit)


@router.get(
    "/{pick_id}", response_model=PersonalPickDetailOut, responses={404: {"model": ErrorOut}}
)
def get_pick(pick_id: str, db: DbSession, settings: AppSettings) -> PersonalPickDetailOut:
    """The pick with every revision (oldest first)."""
    try:
        return personal_picks.get_pick(db, pick_id, provider=settings.data_provider)
    except PickNotFoundError as exc:
        raise _http(exc) from exc


@router.post("/{pick_id}/revisions", response_model=PersonalPickDetailOut, responses=ERRORS)
def revise_pick(
    pick_id: str, request: PersonalPickRevisionIn, db: DbSession, settings: AppSettings, now: Now
) -> PersonalPickDetailOut:
    """Change a pick: stored as a new revision, the earlier ones stay. A revision
    stored after kickoff is a retrospective self-report."""
    try:
        return personal_picks.revise_pick(
            db,
            pick_id,
            request,
            now=now,
            bookmaker=settings.bookmaker,
            provider=settings.data_provider,
        )
    except (PickError, PickNotFoundError, PickConflictError) as exc:
        raise _http(exc) from exc
