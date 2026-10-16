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
from edge_api.services.evaluations import import_report
from edge_api.services.prediction_job import run_prediction_job
from edge_api.timeutil import ensure_utc, utcnow
from edge_ingestion import (
    backtest_cli,
    draw_backtest,
    fatigue_backtest,
    lineup_backtest,
    standings_backtest,
)
from edge_ingestion.jobs import record_failed_run, run_ingestion, run_pipeline
from edge_ingestion.providers import ApiFootballProvider, get_provider
from edge_ingestion.providers.http import ProviderError


def _parse_now(value: str | None) -> datetime:
    if not value:
        return utcnow()
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def check_provider(settings: Settings, now: datetime) -> dict[str, Any]:
    """Fetch and parse without touching the database (use it to verify a new API key).

    Cheap on purpose: catalogue + two days of fixtures + odds for the next day's
    fixtures of a few leagues (~5-10 requests with API-Football).
    """
    provider = get_provider(settings.data_provider, settings=settings, reference_time=now)
    report: dict[str, Any] = {"provider": provider.name, "bookmaker": settings.bookmaker}
    if isinstance(provider, ApiFootballProvider):
        status = provider.status()
        report["account"] = {
            "plan": (status.get("subscription") or {}).get("plan"),
            "active": (status.get("subscription") or {}).get("active"),
            "requests": status.get("requests"),
        }
    leagues = provider.get_leagues()
    fixtures = provider.get_fixtures(now - timedelta(days=1), now + timedelta(days=1))
    upcoming = sorted(
        (f for f in fixtures if f.status == "scheduled" and f.kickoff_at > now),
        key=lambda f: f.kickoff_at,
    )
    by_league = Counter(f.league_provider_id for f in fixtures)
    sample_leagues = [pid for pid, _ in by_league.most_common(3)]
    sample = {
        f.provider_id: f.kickoff_at for f in upcoming if f.league_provider_id in sample_leagues
    }
    odds = provider.get_odds(dict(list(sample.items())[:20]))
    names = {lg.provider_id: f"{lg.country} - {lg.name}" for lg in leagues}
    finished = sorted((f for f in fixtures if f.status == "finished"), key=lambda f: f.kickoff_at)
    report.update(
        leagues=len(leagues),
        leagues_by_type=dict(Counter(lg.type for lg in leagues)),
        leagues_with_odds=sum(1 for lg in leagues if lg.has_odds),
        countries=len({lg.country for lg in leagues}),
        fixtures_last_and_next_24h=len(fixtures),
        fixture_statuses=dict(Counter(f.status for f in fixtures)),
        busiest_leagues=[f"{names.get(pid, pid)}: {n}" for pid, n in by_league.most_common(5)],
        sample_finished_fixture=asdict(finished[-1]) if finished else None,
        odds_snapshots_sampled=len(odds),
        sampled_fixtures_with_primary_bookmaker=len(
            {o.fixture_provider_id for o in odds if o.bookmaker == settings.bookmaker}
        ),
        bookmakers=sorted({o.bookmaker for o in odds}),
    )
    if isinstance(provider, ApiFootballProvider):
        report["requests_used"] = provider.requests_made
        report["requests_left_today"] = provider.daily_remaining
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edge", description="EPL Edge Lab data jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("seed", "ingest", "predict", "check-provider"):
        sp = sub.add_parser(name)
        sp.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    backtest_cli.add_arguments(sub.add_parser("backtest", help="walk-forward model evaluation"))
    lineup_backtest.add_arguments(
        sub.add_parser("backtest-lineups", help="does line-up strength improve the model?")
    )
    fatigue_backtest.add_arguments(
        sub.add_parser("backtest-fatigue", help="do rest days / fixture congestion help?")
    )
    standings_backtest.add_arguments(
        sub.add_parser("backtest-standings", help="do league-table stakes help?")
    )
    draw_backtest.add_arguments(
        sub.add_parser("backtest-draws", help="does a rolling draw-rate recalibration help?")
    )
    bf = sub.add_parser("backfill-appearances", help="player minutes of past fixtures")
    bf.add_argument("--days", type=int, default=420, help="how far back (default ~2 seasons)")
    bf.add_argument("--limit", type=int, default=2000, help="fixtures per run")
    bf.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    args = parser.parse_args(argv)

    if args.command == "backtest-lineups":
        configure_logging(get_settings().log_level)
        report = lineup_backtest.run(args)
        print(
            json.dumps({k: report[k] for k in ("lineup_fit", "per_league", "promotion")}, indent=2)
        )
        return 0

    if args.command == "backtest-fatigue":
        configure_logging(get_settings().log_level)
        report = fatigue_backtest.run(args)
        print(
            json.dumps({k: report[k] for k in ("gate", "replication", "qa_reproduction")}, indent=2)
        )
        return 0

    if args.command == "backtest-standings":
        configure_logging(get_settings().log_level)
        report = standings_backtest.run(args)
        print(json.dumps(report["gate"], indent=2))
        return 0

    if args.command == "backtest-draws":
        configure_logging(get_settings().log_level)
        report = draw_backtest.run(args)
        print(json.dumps(report["gate"], indent=2))
        return 0

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
        if args.command == "backfill-appearances":
            result = _backfill_appearances(settings, now, args.days, args.limit)
        else:
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


def _backfill_appearances(settings: Settings, now: datetime, days: int, limit: int) -> dict:
    from edge_api.services.leagues import scoped_league_ids
    from edge_ingestion.team_news import ingest_appearances

    provider = get_provider(settings.data_provider, settings=settings, reference_time=now)
    with session_scope() as session:
        inserted = ingest_appearances(
            session,
            provider,
            now=now,
            scope=scoped_league_ids(session, provider.name, settings.team_news_leagues),
            limit=limit,
            lookback=timedelta(days=days),
        )
    return {"appearances_inserted": inserted, "requests_used": provider.requests_made}


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
                    # Before the pipeline: a pick published by it cites this backtest.
                    imported = import_report(session)
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
                    result["evaluation_imported"] = imported
                else:
                    result = asdict(run_ingestion(session, provider, now=now, settings=settings))
    return result


if __name__ == "__main__":
    sys.exit(main())
