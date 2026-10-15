"""Pre-match prediction job (idempotent, append-only).

Runs per data provider: synthetic (mock) and real fixtures are never mixed.
For every upcoming fixture with a market snapshot:
  1. fit the baseline model on results known *before now* (no look-ahead)
  2. pick the latest odds snapshot captured at/before now
  3. INSERT the prediction ... ON CONFLICT (idempotency key) DO NOTHING

Re-running with unchanged inputs is a no-op. New odds or new results produce
a new snapshot row; existing rows are never modified (DB trigger enforces it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.db.models import Fixture, FixtureStatus, OddsSnapshot, Prediction
from edge_api.services.model_registry import get_or_create_model_version
from edge_api.timeutil import ensure_utc
from edge_ml.core import MatchResult
from edge_ml.model import PoissonEloModel

logger = logging.getLogger(__name__)

DEFAULT_HORIZON = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class PredictionJobResult:
    model_version_id: int
    candidates: int
    created: int
    unchanged: int
    skipped_no_odds: int


def _training_matches(session: Session, now: datetime, provider: str) -> list[MatchResult]:
    stmt = select(Fixture).where(
        Fixture.provider == provider,
        Fixture.status == FixtureStatus.FINISHED.value,
        Fixture.kickoff_at < now,
        Fixture.home_score.is_not(None),
        Fixture.away_score.is_not(None),
    )
    return [
        MatchResult(
            home=str(f.home_team_id),
            away=str(f.away_team_id),
            home_goals=f.home_score,  # type: ignore[arg-type]
            away_goals=f.away_score,  # type: ignore[arg-type]
            kickoff_at=f.kickoff_at,
        )
        for f in session.scalars(stmt).unique()
    ]


def _latest_snapshot(
    session: Session, fixture: Fixture, bookmaker: str, now: datetime
) -> OddsSnapshot | None:
    stmt = (
        select(OddsSnapshot)
        .where(
            OddsSnapshot.fixture_id == fixture.id,
            OddsSnapshot.bookmaker == bookmaker,
            OddsSnapshot.captured_at <= now,
            OddsSnapshot.captured_at < fixture.kickoff_at,
        )
        .order_by(OddsSnapshot.captured_at.desc(), OddsSnapshot.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def run_prediction_job(
    session: Session,
    *,
    now: datetime,
    bookmaker: str,
    provider: str,
    horizon: timedelta = DEFAULT_HORIZON,
    model: PoissonEloModel | None = None,
) -> PredictionJobResult:
    now = ensure_utc(now)
    matches = _training_matches(session, now, provider)
    model = (model or PoissonEloModel()).fit(matches, as_of=now)
    model_version = get_or_create_model_version(session, model)
    results_as_of = max((m.kickoff_at for m in matches), default=None)

    upcoming = session.scalars(
        select(Fixture)
        .where(
            Fixture.provider == provider,
            Fixture.status == FixtureStatus.SCHEDULED.value,
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= now + horizon,
        )
        .order_by(Fixture.kickoff_at, Fixture.id)
    ).unique()

    candidates = created = skipped_no_odds = 0
    for fixture in upcoming:
        candidates += 1
        snapshot = _latest_snapshot(session, fixture, bookmaker, now)
        if snapshot is None:
            skipped_no_odds += 1
            continue
        out = model.predict(str(fixture.home_team_id), str(fixture.away_team_id))
        # Deterministic "as of": the newest input timestamp, NOT wall-clock time,
        # so identical inputs always map to the same idempotency key.
        input_as_of = max(t for t in (snapshot.captured_at, results_as_of) if t is not None)
        stmt = (
            insert(Prediction)
            .values(
                fixture_id=fixture.id,
                model_version_id=model_version.id,
                market_odds_snapshot_id=snapshot.id,
                input_data_as_of=input_as_of,
                probability_home=out.probabilities.home,
                probability_draw=out.probabilities.draw,
                probability_away=out.probabilities.away,
                expected_goals_home=out.expected_goals_home,
                expected_goals_away=out.expected_goals_away,
                features=out.features,
            )
            .on_conflict_do_nothing(constraint="uq_predictions_idempotency_key")
            .returning(Prediction.id)
        )
        if session.execute(stmt).scalar_one_or_none() is not None:
            created += 1

    result = PredictionJobResult(
        model_version_id=model_version.id,
        candidates=candidates,
        created=created,
        unchanged=candidates - created - skipped_no_odds,
        skipped_no_odds=skipped_no_odds,
    )
    logger.info("prediction job finished %s", result)
    return result
