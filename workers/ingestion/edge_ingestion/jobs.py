"""Idempotent ingestion jobs: provider DTOs -> PostgreSQL.

- teams / fixtures: UPSERT on (provider, provider_id); rows are only touched
  when a value actually changed, so a no-op re-run writes nothing.
- odds snapshots: append-only INSERT ... ON CONFLICT DO NOTHING on
  (fixture, bookmaker, market, captured_at).
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Result, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import Fixture, FixtureStatus, IngestionRun, OddsSnapshot, Team
from edge_api.services.picks import local_day, publish_daily_pick, settle_daily_picks
from edge_api.services.prediction_job import PredictionJobResult, run_prediction_job
from edge_api.timeutil import ensure_utc, utcnow
from edge_ingestion.providers.base import FootballDataProvider

logger = logging.getLogger(__name__)

# Serialises concurrent pipeline runs (CLI seed vs. Celery beat) per database.
PIPELINE_LOCK_KEY = 7_243_001
VALID_STATUSES = {s.value for s in FixtureStatus}
# Results window kept in sync with the DB (history for rating fits + upcoming fixtures).
INGEST_LOOKBACK = timedelta(days=400)
INGEST_LOOKAHEAD = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    teams_changed: int
    fixtures_changed: int
    odds_inserted: int
    odds_rejected: int


@dataclass(frozen=True, slots=True)
class PipelineResult:
    ingestion: IngestionResult
    predictions: PredictionJobResult
    picks: dict[str, Any] = field(default_factory=dict)


def _key_map(rows: Result[tuple[str, int]]) -> dict[str, int]:
    return {provider_id: pk for provider_id, pk in rows}


def ingest_teams(session: Session, provider: FootballDataProvider) -> int:
    rows = [
        {
            "provider": provider.name,
            "provider_id": t.provider_id,
            "name": t.name,
            "short_name": t.short_name,
            "league": provider.league,
        }
        for t in provider.get_teams()
    ]
    if not rows:
        return 0
    stmt = insert(Team).values(rows)
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        constraint="uq_teams_provider_key",
        set_={"name": ex.name, "short_name": ex.short_name, "updated_at": func.now()},
        where=or_(Team.name != ex.name, Team.short_name != ex.short_name),
    ).returning(Team.id)
    return len(session.execute(stmt).all())


def ingest_fixtures(
    session: Session, provider: FootballDataProvider, date_from: datetime, date_to: datetime
) -> int:
    team_ids = _key_map(
        session.execute(select(Team.provider_id, Team.id).where(Team.provider == provider.name))
    )
    rows = []
    for f in provider.get_fixtures(date_from, date_to):
        if f.status not in VALID_STATUSES:
            logger.warning("skip fixture %s: invalid status %r", f.provider_id, f.status)
            continue
        home, away = team_ids.get(f.home_team_provider_id), team_ids.get(f.away_team_provider_id)
        if home is None or away is None:
            logger.warning("skip fixture %s: unknown team", f.provider_id)
            continue
        rows.append(
            {
                "provider": provider.name,
                "provider_id": f.provider_id,
                "league": provider.league,
                "season": f.season,
                "round": f.round,
                "kickoff_at": ensure_utc(f.kickoff_at),
                "home_team_id": home,
                "away_team_id": away,
                "status": f.status,
                "home_score": f.home_score,
                "away_score": f.away_score,
            }
        )
    if not rows:
        return 0
    stmt = insert(Fixture).values(rows)
    ex = stmt.excluded
    mutable = ("season", "round", "kickoff_at", "status", "home_score", "away_score")
    stmt = stmt.on_conflict_do_update(
        constraint="uq_fixtures_provider_key",
        set_={**{c: getattr(ex, c) for c in mutable}, "updated_at": func.now()},
        where=or_(*(getattr(Fixture, c).is_distinct_from(getattr(ex, c)) for c in mutable)),
    ).returning(Fixture.id)
    return len(session.execute(stmt).all())


def _valid_odds(*odds: float) -> bool:
    return all(math.isfinite(o) and o > 1.0 for o in odds)


def ingest_odds(
    session: Session, provider: FootballDataProvider, date_from: datetime, date_to: datetime
) -> tuple[int, int]:
    fixture_ids = _key_map(
        session.execute(
            select(Fixture.provider_id, Fixture.id).where(
                Fixture.provider == provider.name,
                Fixture.kickoff_at >= date_from,
                Fixture.kickoff_at < date_to,
            )
        )
    )
    rows, rejected = [], 0
    for o in provider.get_odds(list(fixture_ids)):
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
    inserted = 0
    for i in range(0, len(rows), 1000):  # keep statements reasonably sized
        stmt = (
            insert(OddsSnapshot)
            .values(rows[i : i + 1000])
            .on_conflict_do_nothing(constraint="uq_odds_snapshots_snapshot_key")
            .returning(OddsSnapshot.id)
        )
        inserted += len(session.execute(stmt).all())
    if rejected:
        logger.warning("rejected %d odds rows (unknown fixture or invalid price)", rejected)
    return inserted, rejected


def run_ingestion(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    lookback: timedelta = INGEST_LOOKBACK,
    lookahead: timedelta = INGEST_LOOKAHEAD,
) -> IngestionResult:
    now = ensure_utc(now)
    date_from, date_to = now - lookback, now + lookahead
    teams = ingest_teams(session, provider)
    fixtures = ingest_fixtures(session, provider, date_from, date_to)
    odds, rejected = ingest_odds(session, provider, date_from, date_to)
    result = IngestionResult(teams, fixtures, odds, rejected)
    logger.info("ingestion finished provider=%s %s", provider.name, result)
    return result


def run_pipeline(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    bookmaker: str,
    settings: Settings | None = None,
) -> PipelineResult:
    """Ingest, predict, settle and (when due) publish Today's Pick in one
    transaction, guarded by an advisory lock. Each run is logged."""
    started = utcnow()
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": PIPELINE_LOCK_KEY})
    ingestion = run_ingestion(session, provider, now=now)
    predictions = run_prediction_job(session, now=now, bookmaker=bookmaker, provider=provider.name)
    session.add(
        IngestionRun(
            provider=provider.name,
            started_at=started,
            finished_at=utcnow(),
            status="success",
            counts={"ingestion": asdict(ingestion), "predictions": asdict(predictions)},
        )
    )
    session.flush()
    picks: dict[str, Any] = {}
    if settings is not None:
        picks["settled"] = settle_daily_picks(session, settings, now)
        if now >= local_day(now, settings).publish_at:
            picks["published"] = publish_daily_pick(session, settings, now).status
    return PipelineResult(ingestion, predictions, picks)


def record_failed_run(provider: str, started: datetime, error: BaseException) -> None:
    """Log a failed run in its own transaction (the pipeline's was rolled back)."""
    from edge_api.db.session import session_scope

    with session_scope() as s:
        s.add(
            IngestionRun(
                provider=provider,
                started_at=started,
                finished_at=utcnow(),
                status="failed",
                error=f"{type(error).__name__}: {error}"[:2000],
            )
        )
