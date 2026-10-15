"""Command line entry point.

    python -m edge_ingestion.cli seed            # ingest + predictions (configured provider)
    python -m edge_ingestion.cli ingest          # provider -> DB only
    python -m edge_ingestion.cli predict         # predictions only
    python -m edge_ingestion.cli check-provider  # dry run: fetch + parse, no DB writes
    ... --now 2026-10-15T09:00:00Z               # pin the reference time

seed/ingest/predict are idempotent; running them repeatedly never duplicates rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from edge_api.config import Settings, get_settings
from edge_api.db.session import session_scope
from edge_api.logging_setup import configure_logging
from edge_api.services.prediction_job import run_prediction_job
from edge_api.timeutil import ensure_utc, utcnow
from edge_ingestion.jobs import run_ingestion, run_pipeline
from edge_ingestion.providers import ApiFootballProvider, get_provider
from edge_ingestion.providers.http import ProviderError


def _parse_now(value: str | None) -> datetime:
    if not value:
        return utcnow()
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def check_provider(settings: Settings, now: datetime) -> dict[str, Any]:
    """Fetch and parse without touching the database (use it to verify a new API key)."""
    provider = get_provider(settings.data_provider, settings=settings, reference_time=now)
    report: dict[str, Any] = {"provider": provider.name, "bookmaker": settings.bookmaker}
    if isinstance(provider, ApiFootballProvider):
        status = provider.status()
        report["account"] = {
            "plan": (status.get("subscription") or {}).get("plan"),
            "active": (status.get("subscription") or {}).get("active"),
            "requests": status.get("requests"),
        }
        report["seasons"] = provider.seasons
    teams = provider.get_teams()
    fixtures = provider.get_fixtures(now - timedelta(days=400), now + timedelta(days=30))
    upcoming = [
        f for f in fixtures if f.status == "scheduled" and f.kickoff_at <= now + timedelta(days=14)
    ]
    odds = provider.get_odds([f.provider_id for f in upcoming])
    report.update(
        teams=len(teams),
        fixtures=len(fixtures),
        fixture_statuses=dict(Counter(f.status for f in fixtures)),
        upcoming_14d=len(upcoming),
        odds_snapshots=len(odds),
        fixtures_with_primary_bookmaker_odds=len(
            {o.fixture_provider_id for o in odds if o.bookmaker == settings.bookmaker}
        ),
        bookmakers=sorted({o.bookmaker for o in odds}),
    )
    if isinstance(provider, ApiFootballProvider):
        report["requests_used"] = provider.requests_made
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edge", description="EPL Edge Lab data jobs")
    parser.add_argument("command", choices=["seed", "ingest", "predict", "check-provider"])
    parser.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    now = _parse_now(args.now)

    try:
        result = _run(args.command, settings, now)
    except (ProviderError, ValueError) as exc:
        # Clean, secret-free failure message instead of a traceback.
        print(json.dumps({"command": args.command, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"command": args.command, "now": now.isoformat(), "result": result}))
    return 0


def _run(command: str, settings: Settings, now: datetime) -> dict[str, Any]:
    if command == "check-provider":
        result: dict[str, Any] = check_provider(settings, now)
    else:
        with session_scope() as session:
            if command == "predict":
                result = asdict(
                    run_prediction_job(
                        session,
                        now=now,
                        bookmaker=settings.bookmaker,
                        provider=settings.data_provider,
                    )
                )
            else:
                provider = get_provider(
                    settings.data_provider, settings=settings, reference_time=now
                )
                if command == "seed":
                    result = asdict(
                        run_pipeline(session, provider, now=now, bookmaker=settings.bookmaker)
                    )
                else:
                    result = asdict(run_ingestion(session, provider, now=now))
    return result


if __name__ == "__main__":
    sys.exit(main())
