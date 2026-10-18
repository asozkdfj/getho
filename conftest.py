"""Shared pytest fixtures.

DB-backed tests use TEST_DATABASE_URL (default: local edge_test database). The
schema is rebuilt with Alembic once per session (downgrade base -> upgrade head,
which also exercises the migrations) and every table is TRUNCATEd between tests.

Wall clock: rows stamped by the database (``created_at``, ``published_at``, ...)
and the pipeline's run log would otherwise carry the real time, which is days
after the fixed test clock, so every input would look recorded after the
decision time. Tests therefore run on a test wall clock: column defaults that
call now() read ``edge.test_now`` (set to NOW on every connection), and the
pipeline's ``utcnow`` returns NOW. Production keeps the database time.

If PostgreSQL is unreachable the DB tests are skipped locally, but CI sets
REQUIRE_DB_TESTS=1 so a missing database fails the build instead.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).parent
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://edge:edge@localhost:5432/edge_test"
)
# A fixed "now" keeps every DB test deterministic (Thursday, inside a mock round).
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
TABLES = (
    "shadow_forecasts, daily_pick_events, daily_picks, model_evaluations, ingestion_runs, "
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
    _install_test_clock(eng)
    yield eng
    eng.dispose()


def _install_test_clock(eng: Engine) -> None:
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION edge_test_now() RETURNS timestamptz LANGUAGE sql "
                "STABLE AS $$ SELECT COALESCE(NULLIF(current_setting('edge.test_now', true), "
                "'')::timestamptz, now()) $$"
            )
        )
        columns = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND column_default = 'now()'"
            )
        ).all()
        for table, column in columns:
            conn.execute(
                text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET DEFAULT edge_test_now()')
            )

    @event.listens_for(eng, "connect")
    def _set_clock(dbapi_conn, _record):
        with dbapi_conn.cursor() as cur:
            cur.execute("SELECT set_config('edge.test_now', %s, false)", (NOW.isoformat(),))
        dbapi_conn.commit()

    eng.dispose()  # reconnect so every pooled connection carries the clock


def set_test_wall_clock(session: Session, at: datetime) -> None:
    """Move the database wall clock for this session's connection (reset to NOW
    at the start of every test)."""
    session.execute(text("SELECT set_config('edge.test_now', :t, false)"), {"t": at.isoformat()})


@pytest.fixture(autouse=True)
def _pipeline_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from edge_ingestion import jobs

    monkeypatch.setattr(jobs, "utcnow", lambda: NOW)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    engine.dispose()  # drop connections whose wall clock a test moved
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
