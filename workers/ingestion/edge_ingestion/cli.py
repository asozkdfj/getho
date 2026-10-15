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
from datetime import UTC, datetime, timedelta
from typing import Any

from edge_api.config import Settings, get_settings
from edge_api.db.session import session_scope
from edge_api.logging_setup import configure_logging
from edge_api.services.evaluations import import_report
from edge_api.services.prediction_job import run_prediction_job
from edge_api.timeutil import ensure_utc, utcnow
from edge_ingestion import backtest_cli
from edge_ingestion.jobs import (
    INGEST_LOOKAHEAD,
    INGEST_LOOKBACK,
    record_failed_run,
    run_ingestion,
    run_pipeline,
)
from edge_ingestion.providers import ApiFootballProvider, get_provider
from edge_ingestion.providers.http import ProviderError

EVERYTHING = (datetime(1900, 1, 1, tzinfo=UTC), datetime(2200, 1, 1, tzinfo=UTC))


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
    # Count everything the provider returned (a pinned past season lies outside the
    # ingestion window), then report the window the real ingestion would use.
    fixtures = provider.get_fixtures(EVERYTHING[0], EVERYTHING[1])
    window = (now - INGEST_LOOKBACK, now + INGEST_LOOKAHEAD)
    in_window = [f for f in fixtures if window[0] <= f.kickoff_at < window[1]]
    upcoming = [
        f
        for f in fixtures
        if f.status == "scheduled" and now < f.kickoff_at <= now + timedelta(days=14)
    ]
    odds = provider.get_odds([f.provider_id for f in upcoming])
    team_ids = {t.provider_id for t in teams}
    finished = sorted((f for f in fixtures if f.status == "finished"), key=lambda f: f.kickoff_at)
    report.update(
        teams=len(teams),
        fixtures=len(fixtures),
        fixtures_by_season=dict(Counter(f.season for f in fixtures)),
        fixtures_in_ingest_window=len(in_window),
        fixture_statuses=dict(Counter(f.status for f in fixtures)),
        fixtures_with_unknown_team=sum(
            1 for f in fixtures if {f.home_team_provider_id, f.away_team_provider_id} - team_ids
        ),
        sample_finished_fixture=asdict(finished[-1]) if finished else None,
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
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("seed", "ingest", "predict", "check-provider"):
        sp = sub.add_parser(name)
        sp.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    backtest_cli.add_arguments(sub.add_parser("backtest", help="walk-forward model evaluation"))
    args = parser.parse_args(argv)

    if args.command == "backtest":
        configure_logging(get_settings().log_level)
        report = backtest_cli.run(args)
        for period in ("validation", "test"):
            print(backtest_cli.summary_table(report, period))
            print()
        for key in ("promotion", "promotion_calibrated"):
            if key in report:
                print(f"{key}: {report[key]['promote']} - {'; '.join(report[key]['reasons'])}")
        return 0

    settings = get_settings()
    configure_logging(settings.log_level)
    now = _parse_now(args.now)

    try:
        result = _run(args.command, settings, now)
    except (ProviderError, ValueError) as exc:
        # Clean, secret-free failure message instead of a traceback.
        print(json.dumps({"command": args.command, "error": str(exc)}), file=sys.stderr)
        return 2
    # default=str: results may contain datetimes (e.g. the sample fixture)
    print(
        json.dumps(
            {"command": args.command, "now": now.isoformat(), "result": result},
            default=str,
            ensure_ascii=False,
        )
    )
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
                    started = utcnow()
                    try:
                        pipeline = run_pipeline(
                            session,
                            provider,
                            now=now,
                            bookmaker=settings.bookmaker,
                            settings=settings,
                        )
                    except Exception as exc:
                        session.rollback()
                        record_failed_run(provider.name, started, exc)
                        raise
                    result = asdict(pipeline)
                    result["evaluation_imported"] = import_report(session)
                else:
                    result = asdict(run_ingestion(session, provider, now=now))
    return result


if __name__ == "__main__":
    sys.exit(main())
