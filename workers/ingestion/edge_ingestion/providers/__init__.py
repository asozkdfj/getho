from __future__ import annotations

from edge_ingestion.providers.base import FootballDataProvider
from edge_ingestion.providers.mock import MockProvider


def get_provider(name: str) -> FootballDataProvider:
    """Provider factory. Only `mock` exists in the MVP (see docs/TODO.md)."""
    if name == "mock":
        return MockProvider()
    raise ValueError(f"unknown data provider: {name!r} (available: mock)")


__all__ = ["FootballDataProvider", "MockProvider", "get_provider"]
