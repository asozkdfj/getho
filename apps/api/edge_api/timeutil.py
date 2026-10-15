from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Reject naive datetimes instead of guessing their timezone."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime: all timestamps must be timezone-aware")
    return dt.astimezone(UTC)
