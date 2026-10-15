from __future__ import annotations

from fastapi import APIRouter, HTTPException

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.schemas import CombinationOut, CombinationRequest, ErrorOut
from edge_api.services.combinations import CombinationError, analyse_combination

router = APIRouter(prefix="/combinations", tags=["combinations"])


@router.post("/analyze", response_model=CombinationOut, responses={422: {"model": ErrorOut}})
def analyze(
    request: CombinationRequest, db: DbSession, settings: AppSettings, now: Now
) -> CombinationOut:
    """Analyse 2-3 selections from *different* fixtures (independence approximation)."""
    try:
        return analyse_combination(db, request, now=now, threshold=settings.value_threshold)
    except CombinationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
