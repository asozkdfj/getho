"""Shared pytest fixtures.

DB-backed tests use TEST_DATABASE_URL (default: local edge_test database). The
schema is rebuilt with Alembic once per session (downgrade base -> upgrade head,
which also exercises the migrations) and every table is TRUNCATEd between tests.

If PostgreSQL is unreachable the DB tests are skipped locally, but CI sets
REQUIRE_DB_TESTS=1 so a missing database fails the build instead.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).parent
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://edge:edge@localhost:5432/edge_test"
)
# A fixed "now" keeps every DB test deterministic (Thursday, inside a mock round).
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
TABLES = (
    "daily_pick_events, daily_picks, model_evaluations, ingestion_runs, "
    "team_news_snapshots, player_appearances, "
    "predictions, odds_snapshots, fixtures, teams, leagues, model_versions"
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    from alembic import command
    from alembic.config import Config

    from edge_api.db.session import make_engine

    eng = make_engine(TEST_DATABASE_URL)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        if os.getenv("REQUIRE_DB_TESTS") == "1":
            pytest.fail(f"PostgreSQL required but unreachable: {type(exc).__name__}")
        pytest.skip("PostgreSQL not reachable (set TEST_DATABASE_URL to run DB tests)")

    cfg = Config(str(ROOT / "apps/api/alembic.ini"))
    cfg.attributes["url"] = TEST_DATABASE_URL
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def now() -> datetime:
    return NOW
