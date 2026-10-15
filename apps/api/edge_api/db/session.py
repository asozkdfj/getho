from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from edge_api.config import get_settings


def make_engine(url: str, **kwargs: Any) -> Engine:
    engine = create_engine(url, pool_pre_ping=True, **kwargs)

    @event.listens_for(engine, "connect")
    def _force_utc(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        # Every session talks UTC regardless of server defaults.
        with dbapi_conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url.get_secret_value())


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """Transactional scope for jobs/CLI: commit on success, rollback on error."""
    session = (factory or get_sessionmaker())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
