from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from edge_api.api.routes import (
    combinations,
    fixtures,
    health,
    highlights,
    leagues,
    performance,
    personal_picks,
    picks,
    research,
    review,
)
from edge_api.config import get_settings
from edge_api.logging_setup import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="EPL Edge Lab API",
        version="0.1.0",
        description=(
            "EPL 1X2 확률 분석 API. 모델 확률·시장 공정확률·Edge·EV를 제공합니다. "
            "확률은 추정치이며 결과를 보장하지 않습니다. 베팅 실행 기능은 없습니다."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(leagues.router)
    app.include_router(fixtures.router)
    app.include_router(highlights.router)
    app.include_router(picks.router)
    app.include_router(performance.router)
    app.include_router(combinations.router)
    app.include_router(review.router)
    app.include_router(research.router)
    app.include_router(personal_picks.router)
    return app


app = create_app()
