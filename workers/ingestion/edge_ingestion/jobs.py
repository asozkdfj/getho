"""Idempotent ingestion jobs: provider DTOs -> PostgreSQL.

- leagues / teams / fixtures: UPSERT on (provider, provider_id); rows are only
  touched when a value actually changed, so a no-op re-run writes nothing.
- odds snapshots: append-only INSERT ... ON CONFLICT DO NOTHING on
  (fixture, bookmaker, market, captured_at).

Each run refreshes a short rolling window of fixtures for every league (cheap:
the real provider serves one day of all leagues per request) and backfills the
past results of leagues that do not have them yet, a bounded number per run.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Result, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from edge_api.catalog import featured_rank
from edge_api.config import Settings
from edge_api.db.models import (
    Fixture,
    FixtureStatus,
    IngestionRun,
    League,
    LeagueType,
    OddsSnapshot,
    Team,
)
from edge_api.services.picks import local_day, publish_daily_pick, settle_daily_picks
from edge_api.services.prediction_job import PredictionJobResult, run_prediction_job
from edge_api.timeutil import ensure_utc, utcnow
from edge_ingestion.providers.base import FixtureData, FootballDataProvider, LeagueData, TeamData
from edge_ingestion.providers.http import ProviderError
from edge_ingestion.team_news import ingest_team_news

logger = logging.getLogger(__name__)

# Serialises concurrent pipeline runs (CLI seed vs. Celery beat) per database.
PIPELINE_LOCK_KEY = 7_243_001
VALID_STATUSES = {s.value for s in FixtureStatus}
# Rolling window refreshed on every run (results of the last days + the coming week).
RECENT_LOOKBACK = timedelta(days=3)
INGEST_LOOKAHEAD = timedelta(days=8)
DEFAULT_BACKFILL_PER_RUN = 40
DEFAULT_ODDS_LOOKAHEAD_DAYS = 14
# A fixture still "scheduled"/"live" this long after kickoff should have a result;
# if the rolling window no longer returns it, it was moved (or dropped) and is
# looked up by id. Only recent ones, so unplayable history is not re-asked forever.
OVERDUE_AFTER = timedelta(hours=4)
OVERDUE_LOOKBACK = timedelta(days=30)
RECONCILE_PER_RUN = 100
CHUNK = 1000  # rows per INSERT statement


@dataclass(frozen=True, slots=True)
class IngestionResult:
    leagues_changed: int
    teams_changed: int
    fixtures_changed: int
    odds_inserted: int
    odds_rejected: int
    leagues_backfilled: int = 0
    leagues_pending_backfill: int = 0
    fixtures_reconciled: int = 0  # overdue fixtures updated from a lookup by id
    overdue_unresolved: int = 0  # overdue fixtures the provider did not return
    requests: int = 0


@dataclass(frozen=True, slots=True)
class PipelineResult:
    ingestion: IngestionResult
    predictions: PredictionJobResult
    picks: dict[str, Any] = field(default_factory=dict)
    team_news: dict[str, int] = field(default_factory=dict)


def _key_map(rows: Result[tuple[str, int]]) -> dict[str, int]:
    return {provider_id: pk for provider_id, pk in rows}


def _returning_count(session: Session, stmt_for_chunk: Any, rows: list[dict[str, Any]]) -> int:
    changed = 0
    for i in range(0, len(rows), CHUNK):
        changed += len(session.execute(stmt_for_chunk(rows[i : i + CHUNK])).all())
    return changed


# ------------------------------------------------------------------ leagues
def ingest_leagues(
    session: Session, provider: FootballDataProvider
) -> tuple[int, list[LeagueData]]:
    leagues = provider.get_leagues()
    rows = [
        {
            "provider": provider.name,
            "provider_id": lg.provider_id,
            "name": lg.name,
            "country": lg.country,
            "country_code": lg.country_code,
            "type": lg.type if lg.type in (t.value for t in LeagueType) else "league",
            "current_season": lg.season,
            "season_year": lg.season_year,
            "has_odds": lg.has_odds,
            "logo_url": lg.logo_url,
            "flag_url": lg.flag_url,
        }
        for lg in {lg.provider_id: lg for lg in leagues}.values()
    ]
    mutable = (
        "name",
        "country",
        "country_code",
        "type",
        "current_season",
        "season_year",
        "has_odds",
        "logo_url",
        "flag_url",
    )

    def stmt(chunk: list[dict[str, Any]]) -> Any:
        ins = insert(League).values(chunk)
        ex = ins.excluded
        return ins.on_conflict_do_update(
            constraint="uq_leagues_provider_key",
            set_={**{c: getattr(ex, c) for c in mutable}, "updated_at": func.now()},
            where=or_(*(getattr(League, c).is_distinct_from(getattr(ex, c)) for c in mutable)),
        ).returning(League.id)

    return _returning_count(session, stmt, rows), leagues


# -------------------------------------------------------------------- teams
def _upsert_teams(session: Session, provider: str, teams: Iterable[TeamData]) -> int:
    rows = [
        {
            "provider": provider,
            "provider_id": t.provider_id,
            "name": t.name,
            "short_name": t.short_name[:10],
            "logo_url": t.logo_url,
        }
        for t in {t.provider_id: t for t in teams}.values()
    ]

    def stmt(chunk: list[dict[str, Any]]) -> Any:
        ins = insert(Team).values(chunk)
        ex = ins.excluded
        # short_name is only set on insert: a provider-curated code (older rows)
        # must not be replaced by a code derived from the name.
        return ins.on_conflict_do_update(
            constraint="uq_teams_provider_key",
            set_={"name": ex.name, "logo_url": ex.logo_url, "updated_at": func.now()},
            where=or_(Team.name != ex.name, Team.logo_url.is_distinct_from(ex.logo_url)),
        ).returning(Team.id)

    return _returning_count(session, stmt, rows)


# ----------------------------------------------------------------- fixtures
def ingest_fixtures(
    session: Session, provider: str, fixtures: list[FixtureData]
) -> tuple[int, int]:
    """Upsert the teams and fixtures. Returns (teams_changed, fixtures_changed)."""
    league_ids = _key_map(
        session.execute(select(League.provider_id, League.id).where(League.provider == provider))
    )
    valid = []
    for f in fixtures:
        if f.status not in VALID_STATUSES:
            logger.warning("skip fixture %s: invalid status %r", f.provider_id, f.status)
        elif f.league_provider_id not in league_ids:
            logger.warning(
                "skip fixture %s: unknown league %s", f.provider_id, f.league_provider_id
            )
        elif f.home_team.provider_id == f.away_team.provider_id:
            logger.warning("skip fixture %s: same team twice", f.provider_id)
        else:
            valid.append(f)
    teams_changed = _upsert_teams(
        session, provider, (t for f in valid for t in (f.home_team, f.away_team))
    )
    team_ids = _key_map(
        session.execute(select(Team.provider_id, Team.id).where(Team.provider == provider))
    )
    rows = [
        {
            "provider": provider,
            "provider_id": f.provider_id,
            "league_id": league_ids[f.league_provider_id],
            "season": f.season,
            "round": f.round,
            "kickoff_at": ensure_utc(f.kickoff_at),
            "home_team_id": team_ids[f.home_team.provider_id],
            "away_team_id": team_ids[f.away_team.provider_id],
            "status": f.status,
            "home_score": f.home_score,
            "away_score": f.away_score,
        }
        for f in {f.provider_id: f for f in valid}.values()
    ]
    mutable = ("league_id", "season", "round", "kickoff_at", "status", "home_score", "away_score")

    def stmt(chunk: list[dict[str, Any]]) -> Any:
        ins = insert(Fixture).values(chunk)
        ex = ins.excluded
        return ins.on_conflict_do_update(
            constraint="uq_fixtures_provider_key",
            set_={**{c: getattr(ex, c) for c in mutable}, "updated_at": func.now()},
            where=or_(*(getattr(Fixture, c).is_distinct_from(getattr(ex, c)) for c in mutable)),
        ).returning(Fixture.id)

    return teams_changed, _returning_count(session, stmt, rows)


def mark_results_synced(session: Session, provider: str, now: datetime) -> None:
    """The rolling window just refreshed covers leagues synced within its lookback."""
    session.execute(
        update(League)
        .where(
            League.provider == provider,
            League.results_synced_at >= now - RECENT_LOOKBACK,
            League.results_synced_at < now,
        )
        .values(results_synced_at=now)
    )


def leagues_needing_history(session: Session, provider: str, now: datetime) -> list[League]:
    """Leagues that could be predicted (league format, odds) and have upcoming
    fixtures, but whose past results are missing or have a gap. Featured first."""
    upcoming = (
        select(Fixture.league_id, func.count().label("n"))
        .where(
            Fixture.provider == provider,
            Fixture.status == FixtureStatus.SCHEDULED.value,
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= now + INGEST_LOOKAHEAD,
        )
        .group_by(Fixture.league_id)
        .subquery()
    )
    rows = session.execute(
        select(League, upcoming.c.n)
        .join(upcoming, upcoming.c.league_id == League.id)
        .where(
            League.provider == provider,
            League.type == LeagueType.LEAGUE.value,
            League.has_odds.is_(True),
            or_(
                League.results_synced_at.is_(None),
                League.results_synced_at < now - RECENT_LOOKBACK,
            ),
        )
    ).all()
    rows.sort(key=lambda r: (featured_rank(provider, r[0].provider_id) or 10_000, -r[1], r[0].id))
    return [league for league, _ in rows]


def backfill_history(
    session: Session,
    provider: FootballDataProvider,
    catalogue: dict[str, LeagueData],
    *,
    now: datetime,
    limit: int,
) -> tuple[int, int, int, int]:
    """Returns (leagues_backfilled, leagues_still_pending, teams_changed, fixtures_changed)."""
    pending = leagues_needing_history(session, provider.name, now)
    done = teams = fixtures = 0
    for league in pending[: max(limit, 0)]:
        data = catalogue.get(league.provider_id)
        if data is None:
            continue
        if not provider.budget_ok():
            logger.warning("request budget low: history backfill continues next run")
            break
        t, f = ingest_fixtures(session, provider.name, provider.get_league_history(data))
        teams, fixtures = teams + t, fixtures + f
        league.results_synced_at = now
        done += 1
    session.flush()
    return done, len(pending) - done, teams, fixtures


def reconcile_overdue_fixtures(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    seen: set[str],
    limit: int = RECONCILE_PER_RUN,
) -> tuple[int, int]:
    """Fixtures stuck "scheduled"/"live" well after kickoff that the refreshed
    window did not return: a match moved to another date (postponed and
    rescheduled) or dropped by the provider. Without this they would stay
    "scheduled" with a past kickoff, and a pick on them would never settle.

    Batches rotate: fixtures never asked about come first, then the ones asked
    about longest ago, so fixtures the provider keeps not returning cannot hold
    the batch and starve the rest. Returns (fixtures_changed, still_unresolved)
    for this batch; the log also reports the whole backlog."""
    overdue = session.scalars(
        select(Fixture.provider_id)
        .where(
            Fixture.provider == provider.name,
            Fixture.status.in_([FixtureStatus.SCHEDULED.value, FixtureStatus.LIVE.value]),
            Fixture.kickoff_at < now - OVERDUE_AFTER,
            Fixture.kickoff_at >= now - OVERDUE_LOOKBACK,
        )
        .order_by(
            Fixture.reconcile_checked_at.asc().nulls_first(),
            Fixture.kickoff_at.desc(),
            Fixture.id,
        )
    ).all()
    backlog = [pid for pid in overdue if pid not in seen]
    missing = backlog[: max(limit, 0)]
    if not missing:
        return 0, 0
    if not provider.budget_ok():
        logger.warning("request budget low: %d overdue fixtures checked next run", len(backlog))
        return 0, len(missing)
    session.execute(
        update(Fixture)
        .where(Fixture.provider == provider.name, Fixture.provider_id.in_(missing))
        .values(reconcile_checked_at=now)
    )
    found = provider.get_fixtures_by_ids(missing)
    _, changed = ingest_fixtures(session, provider.name, found)
    unresolved = len(set(missing) - {f.provider_id for f in found})
    if unresolved or len(backlog) > len(missing):
        logger.warning(
            "overdue fixtures: %d not returned by the provider, %d left for later runs",
            unresolved,
            len(backlog) - len(missing),
        )
    return changed, unresolved


# --------------------------------------------------------------------- odds
def _valid_odds(*odds: float) -> bool:
    return all(math.isfinite(o) and o > 1.0 for o in odds)


def ingest_odds(
    session: Session, provider: FootballDataProvider, *, now: datetime, lookahead: timedelta
) -> tuple[int, int]:
    rows_db = session.execute(
        select(Fixture.provider_id, Fixture.id, Fixture.kickoff_at)
        .join(League, League.id == Fixture.league_id)
        .where(
            Fixture.provider == provider.name,
            Fixture.status == FixtureStatus.SCHEDULED.value,
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= now + lookahead,
            League.has_odds.is_(True),
        )
    ).all()
    fixture_ids = {pid: fid for pid, fid, _ in rows_db}
    kickoffs = {pid: kickoff for pid, _, kickoff in rows_db}
    rows, rejected = [], 0
    for o in provider.get_odds(kickoffs):
        fid = fixture_ids.get(o.fixture_provider_id)
        if fid is None or not _valid_odds(o.odds_home, o.odds_draw, o.odds_away):
            rejected += 1
            continue
        rows.append(
            {
                "fixture_id": fid,
                "provider": provider.name,
                "bookmaker": o.bookmaker,
                "market": o.market,
                "odds_home": o.odds_home,
                "odds_draw": o.odds_draw,
                "odds_away": o.odds_away,
                "captured_at": ensure_utc(o.captured_at),
                "raw_payload": o.raw or None,
            }
        )

    def stmt(chunk: list[dict[str, Any]]) -> Any:
        return (
            insert(OddsSnapshot)
            .values(chunk)
            .on_conflict_do_nothing(constraint="uq_odds_snapshots_snapshot_key")
            .returning(OddsSnapshot.id)
        )

    inserted = _returning_count(session, stmt, rows)
    if rejected:
        logger.warning("rejected %d odds rows (unknown fixture or invalid price)", rejected)
    return inserted, rejected


def run_ingestion(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    settings: Settings | None = None,
) -> IngestionResult:
    now = ensure_utc(now)
    leagues_changed, leagues = ingest_leagues(session, provider)
    recent = provider.get_fixtures(now - RECENT_LOOKBACK, now + INGEST_LOOKAHEAD)
    teams, fixtures = ingest_fixtures(session, provider.name, recent)
    reconciled, unresolved = reconcile_overdue_fixtures(
        session, provider, now=now, seen={f.provider_id for f in recent}
    )
    mark_results_synced(session, provider.name, now)
    backfilled, pending, t2, f2 = backfill_history(
        session,
        provider,
        {lg.provider_id: lg for lg in leagues},
        now=now,
        limit=settings.backfill_leagues_per_run if settings else DEFAULT_BACKFILL_PER_RUN,
    )
    lookahead_days = settings.odds_lookahead if settings else DEFAULT_ODDS_LOOKAHEAD_DAYS
    odds, rejected = ingest_odds(
        session, provider, now=now, lookahead=timedelta(days=lookahead_days)
    )
    result = IngestionResult(
        leagues_changed=leagues_changed,
        teams_changed=teams + t2,
        fixtures_changed=fixtures + f2,
        odds_inserted=odds,
        odds_rejected=rejected,
        leagues_backfilled=backfilled,
        leagues_pending_backfill=pending,
        fixtures_reconciled=reconciled,
        overdue_unresolved=unresolved,
        requests=provider.requests_made,
    )
    logger.info("ingestion finished provider=%s %s", provider.name, result)
    return result


def run_pipeline(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    bookmaker: str,
    settings: Settings | None = None,
    decision_at: datetime | None = None,
) -> PipelineResult:
    """Ingest, predict, settle and (when due) publish Today's Pick in one
    transaction, guarded by an advisory lock. Each run is logged.

    The pick is decided after this run's writes: by default at the later of
    ``now`` and the wall clock, so the predictions and run just recorded count as
    known. A run pinned to a past ``now`` passes ``decision_at=now``; inputs
    recorded after it then fail the quality gate, so a replay cannot publish a
    pick it could not have made at that time."""
    started = utcnow()
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": PIPELINE_LOCK_KEY})
    ingestion = run_ingestion(session, provider, now=now, settings=settings)
    team_news = _team_news_isolated(session, provider, now=now, settings=settings)
    predictions = run_prediction_job(session, now=now, bookmaker=bookmaker, provider=provider.name)
    session.add(
        IngestionRun(
            provider=provider.name,
            started_at=started,
            finished_at=utcnow(),
            status="success",
            counts={
                "ingestion": asdict(ingestion),
                "predictions": asdict(predictions),
                "team_news": team_news,
            },
        )
    )
    session.flush()
    picks: dict[str, Any] = {}
    if settings is not None:
        picks["settled"] = settle_daily_picks(session, settings, now)
        decided = decision_at or max(now, utcnow())
        if decided >= local_day(decided, settings).publish_at:
            picks["published"] = publish_daily_pick(session, settings, decided).status
    return PipelineResult(ingestion, predictions, picks, team_news)


def _team_news_isolated(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    settings: Settings | None,
) -> dict[str, Any]:
    """Line-ups and absences are optional extras: a provider error there is
    logged and recorded in the run, and fixtures, odds, predictions and the pick
    still go ahead (the team-news writes alone are rolled back)."""
    if settings is None:
        return {}
    try:
        with session.begin_nested():
            return asdict(ingest_team_news(session, provider, now=now, settings=settings))
    except ProviderError as exc:
        logger.warning("team news skipped this run: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"[:500]}


def record_failed_run(
    provider: str,
    started: datetime,
    error: BaseException,
    factory: sessionmaker[Session] | None = None,
) -> None:
    """Log a failed run in its own transaction (the pipeline's was rolled back)."""
    from edge_api.db.session import session_scope

    with session_scope(factory) as s:
        s.add(
            IngestionRun(
                provider=provider,
                started_at=started,
                finished_at=utcnow(),
                status="failed",
                error=f"{type(error).__name__}: {error}"[:2000],
            )
        )
