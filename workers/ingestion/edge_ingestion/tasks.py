from __future__ import annotations

from dataclasses import asdict
from typing import Any

from edge_api.config import get_settings
from edge_api.db.session import session_scope
from edge_api.timeutil import utcnow
from edge_ingestion.celery_app import app
from edge_ingestion.jobs import record_failed_run, run_pipeline
from edge_ingestion.providers import get_provider


@app.task(
    name="edge_ingestion.tasks.ingest_and_predict",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def ingest_and_predict() -> dict[str, Any]:
    """Safe to retry: every step is idempotent and runs in one transaction."""
    settings = get_settings()
    now = utcnow()
    try:
        with session_scope() as session:
            result = run_pipeline(
                session,
                get_provider(settings.data_provider, settings=settings, reference_time=now),
                now=now,
                bookmaker=settings.bookmaker,
                settings=settings,
            )
    except Exception as exc:
        record_failed_run(settings.data_provider, now, exc)
        raise
    return asdict(result)
