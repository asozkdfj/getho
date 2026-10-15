from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from edge_api.api.deps import get_db, get_now
from edge_api.main import create_app
from edge_ingestion.jobs import run_pipeline
from edge_ingestion.providers import MockProvider

BOOKMAKER = "mockbook"


@pytest.fixture
def seeded(session_factory, now):
    """Fresh DB with mock data + predictions as of the fixed test clock."""
    with session_factory() as session:
        result = run_pipeline(session, MockProvider(now), now=now, bookmaker=BOOKMAKER)
        session.commit()
    return result


@pytest.fixture
def client(session_factory, now, seeded) -> Iterator[TestClient]:
    app = create_app()

    def _db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_now] = lambda: now
    with TestClient(app) as c:
        yield c
