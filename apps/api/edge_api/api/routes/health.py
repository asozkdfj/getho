from __future__ import annotations

import logging

import redis
from fastapi import APIRouter, Response
from sqlalchemy import text

from edge_api.api.deps import AppSettings, DbSession
from edge_api.schemas import HealthOut
from edge_api.versioning import code_fingerprint, resolve_git_sha

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthOut)
def health(db: DbSession, settings: AppSettings, response: Response) -> HealthOut:
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("database health check failed")
        database = "unavailable"

    redis_status = "ok"
    try:
        client = redis.Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=0.5, socket_timeout=0.5
        )
        client.ping()
    except Exception:
        redis_status = "unavailable"  # non-critical for read APIs

    status = "ok" if database == "ok" else "degraded"
    if status != "ok":
        response.status_code = 503
    return HealthOut(
        status=status,
        database=database,
        redis=redis_status,
        app_env=settings.app_env,
        git_sha=resolve_git_sha(),
        code_fingerprint=code_fingerprint(),
    )
