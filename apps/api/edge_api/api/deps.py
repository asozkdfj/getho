from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from edge_api.config import Settings, get_settings
from edge_api.db.session import get_sessionmaker
from edge_api.timeutil import utcnow


def get_db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def get_now() -> datetime:
    """Overridable clock (tests pin it to make results deterministic)."""
    return utcnow()


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Now = Annotated[datetime, Depends(get_now)]
