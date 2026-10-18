from __future__ import annotations

from fastapi import APIRouter, HTTPException

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.schemas import CombinationOut, CombinationRequest, ErrorOut
from edge_api.services.combinations import (
    CombinationError,
    OutdatedSelectionError,
    analyse_combination,
)

router = APIRouter(prefix="/combinations", tags=["combinations"])


@router.post(
    "/analyze",
    response_model=CombinationOut,
    responses={409: {"model": ErrorOut}, 422: {"model": ErrorOut}},
)
def analyze(
    request: CombinationRequest, db: DbSession, settings: AppSettings, now: Now
) -> CombinationOut:
    """Analyse 2-3 selections from *different* fixtures (independence approximation).
    A selection whose ``prediction_id`` is no longer the latest is refused (409)."""
    try:
        return analyse_combination(db, request, now=now, threshold=settings.value_threshold)
    except OutdatedSelectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CombinationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
