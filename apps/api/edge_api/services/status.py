"""Data freshness / pipeline status for monitoring and the dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import Fixture, IngestionRun, OddsSnapshot, Prediction


def data_status(session: Session, settings: Settings, now: datetime) -> dict[str, Any]:
    provider = settings.data_provider
    runs = session.scalars(
        select(IngestionRun)
        .where(IngestionRun.provider == provider)
        .order_by(IngestionRun.finished_at.desc(), IngestionRun.id.desc())
        .limit(10)
    ).all()
    last_ok = next((r for r in runs if r.status == "success"), None)
    last_odds = session.scalar(
        select(func.max(OddsSnapshot.captured_at))
        .join(Fixture, Fixture.id == OddsSnapshot.fixture_id)
        .where(Fixture.provider == provider, OddsSnapshot.bookmaker == settings.bookmaker)
    )
    last_pred = session.scalar(
        select(func.max(Prediction.created_at))
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .where(Fixture.provider == provider)
    )
    age_h = (now - last_ok.finished_at).total_seconds() / 3600 if last_ok else None
    stale = age_h is None or age_h > settings.ingest_max_age_hours
    return {
        "provider": provider,
        "is_demo": provider == "mock",
        "bookmaker": settings.bookmaker,
        "status": "stale" if stale else "ok",
        "last_success_at": last_ok.finished_at if last_ok else None,
        "last_success_age_hours": age_h,
        "ingest_max_age_hours": settings.ingest_max_age_hours,
        "recent_failures": sum(1 for r in runs if r.status == "failed"),
        "last_error": next((r.error for r in runs if r.status == "failed"), None),
        "latest_odds_captured_at": last_odds,
        "latest_prediction_at": last_pred,
    }
