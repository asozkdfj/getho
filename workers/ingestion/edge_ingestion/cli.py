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
import os
import sys
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from edge_api.config import Settings, get_settings
from edge_api.db.session import session_scope
from edge_api.logging_setup import configure_logging
from edge_api.services.evaluations import import_report
from edge_api.services.prediction_job import run_prediction_job
from edge_api.timeutil import ensure_utc, utcnow
from edge_api.versioning import build_info
from edge_ingestion import (
    backtest_cli,
    calibration_backtest,
    draw_backtest,
    fatigue_backtest,
    goal_markets_backtest,
    lineup_backtest,
    market_backtest,
    standings_backtest,
)
from edge_ingestion.jobs import record_failed_run, run_ingestion, run_pipeline
from edge_ingestion.providers import ApiFootballProvider, get_provider
from edge_ingestion.providers.http import ProviderError


def _parse_now(value: str | None) -> datetime:
    if not value:
        return utcnow()
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def check_xg(settings: Settings, now: datetime, days: int, limit: int) -> dict[str, Any]:
    """Which leagues return post-match xG, without touching the database.

    Recently finished fixtures, spread over the leagues, are fetched with their
    details (/fixtures?ids=, 20 per request): about 1 + ``days`` + limit/20
    requests with API-Football. Only reports what came back; stores nothing.
    """
    provider = get_provider(settings.data_provider, settings=settings, reference_time=now)
    names = {lg.provider_id: f"{lg.country} - {lg.name}" for lg in provider.get_leagues()}
    finished = [
        f for f in provider.get_fixtures(now - timedelta(days=days), now) if f.status == "finished"
    ]
    by_league: dict[str, list[str]] = {}
    for f in sorted(finished, key=lambda f: f.kickoff_at, reverse=True):
        by_league.setdefault(f.league_provider_id, []).append(f.provider_id)
    chosen: list[str] = []
    while len(chosen) < limit and any(by_league.values()):  # round-robin over leagues
        for ids in by_league.values():
            if ids and len(chosen) < limit:
                chosen.append(ids.pop(0))
    stats = provider.get_match_statistics(chosen)
    league_of = {f.provider_id: f.league_provider_id for f in finished}
    per: dict[str, dict[str, Any]] = {}
    for fid in chosen:
        row = per.setdefault(
            league_of[fid],
            {"fixtures_checked": 0, "with_statistics": 0, "with_xg": 0, "sample_xg": None},
        )
        row["fixtures_checked"] += 1
        teams = [s for s in stats if s.fixture_provider_id == fid]
        row["with_statistics"] += bool(teams)
        xg = [s.expected_goals for s in teams if s.expected_goals is not None]
        if len(xg) == 2:
            row["with_xg"] += 1
            row["sample_xg"] = row["sample_xg"] or xg
    report: dict[str, Any] = {
        "provider": provider.name,
        "window_days": days,
        "fixtures_checked": len(chosen),
        "leagues_checked": len(per),
        "leagues_with_xg": sorted(names.get(k, k) for k, v in per.items() if v["with_xg"]),
        "per_league": {names.get(k, k): v for k, v in sorted(per.items())},
        "note": "a league without xG here may still have it for other seasons or matches",
    }
    if isinstance(provider, ApiFootballProvider):
        report["requests_used"] = provider.requests_made
    return report


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


def review_text(settings: Settings, day: str | None, tz: str | None) -> str:
    """Plain-text day review (read-only)."""
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo

    from edge_api.services.review import review_day

    tz = tz or settings.pick_tz
    target = (
        date.fromisoformat(day)
        if day
        else utcnow().astimezone(ZoneInfo(tz)).date() - timedelta(days=1)
    )
    short = {"HOME": "홈승", "DRAW": "무", "AWAY": "원정승"}
    with session_scope() as session:
        data = review_day(session, settings, target, tz)
        s = data.summaries["verified" if not data.demo else "all"]
        lines = [
            f"{target} ({tz}) 경기 복기 · provider={settings.data_provider}",
            f"분석 적중 {s['hits']}/{s['matches']} (기대 {s['expected_hits']:.1f}) · "
            f"시장 적중 {s['market_hits']}/{s['matches']} (기대 {s['market_expected_hits']:.1f})",
        ]
        for i in data.items:
            f = i.fixture
            score = f"{f.home_score}:{f.away_score}" if f.home_score is not None else f.status
            if i.top:
                mark = {True: "O", False: "X", None: "-"}[i.hit]
                pred = f"{short[i.top[0].value]} {i.top[1]:.0%}"
            else:
                mark, pred = "-", "분석 없음"
            match = f"{f.home_team.name} {score} {f.away_team.name}"
            lines.append(f"  [{mark}] {f.league.name}: {match} · {pred}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edge", description="EPL Edge Lab data jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("seed", "ingest", "predict", "check-provider"):
        sp = sub.add_parser(name)
        sp.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    backtest_cli.add_arguments(sub.add_parser("backtest", help="walk-forward model evaluation"))
    rv = sub.add_parser("review", help="a past day: pre-kickoff predictions vs results")
    rv.add_argument("--date", help="local date YYYY-MM-DD (default: yesterday)")
    rv.add_argument("--tz", help="IANA timezone (default: the pick timezone)")
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
    market_backtest.add_arguments(
        sub.add_parser("backtest-market", help="model vs market, and blending with the market")
    )
    calibration_backtest.add_arguments(
        sub.add_parser("backtest-calibration", help="recalibrate the most likely outcome?")
    )
    goal_markets_backtest.add_arguments(
        sub.add_parser("backtest-goal-markets", help="over/under 2.5 and Asian handicap")
    )
    sub.add_parser("code-fingerprint", help="build commit and source fingerprint of this checkout")
    cq = sub.add_parser(
        "collection-quality", help="per pick day: runs, decision, inputs (no outcomes read)"
    )
    cq.add_argument("--start", type=date.fromisoformat, required=True, help="first pick day")
    cq.add_argument("--end", type=date.fromisoformat, required=True, help="last pick day")
    cq.add_argument(
        "--interval-minutes",
        type=float,
        default=float(os.getenv("PIPELINE_INTERVAL_SECONDS", "1800")) / 60,
        help="expected minutes between pipeline runs (default: the worker's schedule)",
    )
    cq.add_argument("--out", type=Path, help="write the JSON report here")
    xg = sub.add_parser("check-xg", help="which leagues return post-match xG (no DB writes)")
    xg.add_argument("--days", type=int, default=3, help="finished fixtures of the last N days")
    xg.add_argument("--limit", type=int, default=40, help="fixtures to fetch details for")
    xg.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    sr = sub.add_parser("shadow-report", help="private shadow forecasts: production vs market")
    sr.add_argument(
        "--start", type=date.fromisoformat, help="first decision day (default: protocol)"
    )
    sr.add_argument("--end", type=date.fromisoformat, help="last decision day (default: protocol)")
    sr.add_argument("--out", type=Path, help="write the JSON report here")
    tc = sub.add_parser(
        "team-news-coverage", help="player information known at each 09:00 decision"
    )
    tc.add_argument("--start", type=date.fromisoformat, required=True, help="first pick day")
    tc.add_argument("--end", type=date.fromisoformat, required=True, help="last pick day")
    tc.add_argument("--out", type=Path, help="write the JSON report here")
    bf = sub.add_parser(
        "backfill-appearances", help="player minutes and team statistics (xG) of past fixtures"
    )
    bf.add_argument("--days", type=int, default=420, help="how far back (default ~2 seasons)")
    bf.add_argument("--limit", type=int, default=2000, help="fixtures per run")
    bf.add_argument("--now", help="ISO-8601 UTC reference time (default: current time)")
    args = parser.parse_args(argv)

    if args.command == "team-news-coverage":
        configure_logging(get_settings().log_level)
        return _team_news_coverage(args)

    if args.command == "collection-quality":
        configure_logging(get_settings().log_level)
        return _collection_quality(args)

    if args.command == "shadow-report":
        configure_logging(get_settings().log_level)
        return _shadow_report(args)

    if args.command == "check-xg":
        configure_logging(get_settings().log_level)
        report = check_xg(get_settings(), _parse_now(args.now), args.days, args.limit)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    if args.command == "code-fingerprint":
        # matches model_versions.code_fingerprint / pick evidence manifest.build
        print(json.dumps(build_info(), indent=2))
        return 0

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

    if args.command == "review":
        print(review_text(get_settings(), args.date, args.tz))
        return 0

    if args.command == "backtest-draws":
        configure_logging(get_settings().log_level)
        report = draw_backtest.run(args)
        print(json.dumps(report["gate"], indent=2))
        return 0

    if args.command == "backtest-market":
        configure_logging(get_settings().log_level)
        report = market_backtest.run(args)
        print(json.dumps(report["gate"], indent=2))
        return 0

    if args.command == "backtest-calibration":
        configure_logging(get_settings().log_level)
        report = calibration_backtest.run(args)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "chosen": report["chosen"],
                    **report["gate"],
                    "standard_gate_passed": report["standard_gate"]["passed"],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "backtest-goal-markets":
        configure_logging(get_settings().log_level)
        report = goal_markets_backtest.run(args)
        print(json.dumps({k: v["decision"] for k, v in report["markets"].items()}, indent=2))
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
            result = _run(args.command, settings, now, pinned=args.now is not None)
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


def _team_news_coverage(args: argparse.Namespace) -> int:
    from edge_api.services.team_news_coverage import coverage_report

    with session_scope() as session:
        report = coverage_report(session, get_settings(), args.start, args.end)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


def _collection_quality(args: argparse.Namespace) -> int:
    from edge_api.services.collection_quality import quality_report

    with session_scope() as session:
        report = quality_report(
            session,
            get_settings(),
            args.start,
            args.end,
            now=utcnow(),
            interval=timedelta(minutes=args.interval_minutes),
        )
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


def _shadow_report(args: argparse.Namespace) -> int:
    from edge_api.services.shadow import shadow_report
    from edge_ml.shadow import EVALUATION_END, EVALUATION_START

    with session_scope() as session:
        report = shadow_report(
            session,
            get_settings().data_provider,
            now=utcnow(),
            start=args.start or EVALUATION_START,
            end=args.end or EVALUATION_END,
        )
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


def _backfill_appearances(settings: Settings, now: datetime, days: int, limit: int) -> dict:
    from edge_api.services.leagues import scoped_league_ids
    from edge_ingestion.team_news import ingest_post_match

    provider = get_provider(settings.data_provider, settings=settings, reference_time=now)
    with session_scope() as session:
        appearances, statistics = ingest_post_match(
            session,
            provider,
            now=now,
            scope=scoped_league_ids(session, provider.name, settings.team_news_leagues),
            limit=limit,
            lookback=timedelta(days=days),
            source="backfill",  # history collected now, not known at the time
        )
    return {
        "appearances_inserted": appearances,
        "statistics_inserted": statistics,
        "requests_used": provider.requests_made,
    }


def _run(
    command: str, settings: Settings, now: datetime, *, pinned: bool = False
) -> dict[str, Any]:
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
                            # a pinned clock decides at that time (see run_pipeline)
                            decision_at=now if pinned else None,
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
