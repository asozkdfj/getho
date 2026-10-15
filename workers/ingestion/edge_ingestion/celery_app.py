"""Celery app. Periodic tasks keep data/predictions fresh and poll line-ups.

Run:  celery -A edge_ingestion.celery_app worker -B --loglevel=INFO
`-B` embeds beat for local dev; run a dedicated beat process in production.
"""

from __future__ import annotations

import os

from celery import Celery

from edge_api.config import get_settings

_settings = get_settings()

app = Celery(
    "edge_ingestion",
    broker=_settings.redis_url.get_secret_value(),
    include=["edge_ingestion.tasks"],
)
app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "ingest-and-predict": {
            "task": "edge_ingestion.tasks.ingest_and_predict",
            "schedule": float(os.getenv("PIPELINE_INTERVAL_SECONDS", "1800")),
        },
        # official line-ups appear ~1h before kickoff: poll more often than the pipeline
        "refresh-lineups": {
            "task": "edge_ingestion.tasks.refresh_lineups",
            "schedule": float(os.getenv("TEAM_NEWS_INTERVAL_SECONDS", "600")),
        },
    },
)
