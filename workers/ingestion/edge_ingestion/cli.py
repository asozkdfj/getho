"""Command line entry point.

    python -m edge_ingestion.cli seed            # ingest mock data + predictions
    python -m edge_ingestion.cli ingest          # provider -> DB only
    python -m edge_ingestion.cli predict         # predictions only
    ... --now 2026-10-15T09:00:00Z               # pin the reference time

All commands are idempotent; running them repeatedly never duplicates rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime

from edge_api.config import get_settings
from edge_api.db.session import session_scope
from edge_api.logging_setup import configure_logging
from edge_api.services.prediction_job import run_prediction_job
from edge_api.timeutil import ensure_utc, utcnow
from edge_ingestion.jobs import run_ingestion, run_pipeline
from edge_ingestion.providers import MockProvider, get_provider
from edge_ingestion.providers.base import FootballDataProvider


def _parse_now(value: str | None) -> datetime:
    if not value:
        return utcnow()
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _provider(name: str, now: datetime) -> FootballDataProvider:
    # The mock needs the reference time so `--now` reproduces a past state.
    return MockProvider(reference_time=now) if name == "mock" else get_provider(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edge", description="EPL Edge Lab data jobs")
    parser.add_argument("command", choices=["seed", "ingest", "predict"])
    parser.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    now = _parse_now(args.now)

    with session_scope() as session:
        if args.command == "seed":
            result = asdict(
                run_pipeline(
                    session,
                    _provider(settings.data_provider, now),
                    now=now,
                    bookmaker=settings.primary_bookmaker,
                )
            )
        elif args.command == "ingest":
            result = asdict(run_ingestion(session, _provider(settings.data_provider, now), now=now))
        else:
            result = asdict(
                run_prediction_job(session, now=now, bookmaker=settings.primary_bookmaker)
            )
    print(json.dumps({"command": args.command, "now": now.isoformat(), "result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
