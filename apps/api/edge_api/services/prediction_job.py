"""Pre-match prediction job (idempotent, append-only).

Runs per data provider (synthetic and real fixtures are never mixed) and per
league: every league gets its own fit of the same model, trained only on that
league's results. Cups are skipped: their teams come from different leagues,
so one table of strengths does not describe them. For every upcoming league
fixture with a market snapshot:
  1. fit the model on the league's results known *before now* (no look-ahead)
  2. pick the latest odds snapshot captured at/before now
  3. INSERT the prediction ... ON CONFLICT (idempotency key) DO NOTHING

Re-running with unchanged inputs is a no-op. New odds or new results produce
a new snapshot row; existing rows are never modified (DB trigger enforces it).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.db.models import Fixture, FixtureStatus, League, LeagueType, OddsSnapshot, Prediction
from edge_api.services import queries
from edge_api.services.model_registry import get_or_create_model_version
from edge_api.timeutil import ensure_utc
from edge_ml.core import MatchResult
from edge_ml.model import PoissonEloModel

logger = logging.getLogger(__name__)

DEFAULT_HORIZON = timedelta(days=14)
# Fewer results than this and a league's ratings are mostly priors: no prediction.
MIN_TRAINING_MATCHES = 30


@dataclass(frozen=True, slots=True)
class PredictionJobResult:
    model_version_id: int
    candidates: int
    created: int
    unchanged: int
    skipped_no_odds: int
    leagues_predicted: int = 0
    skipped_cup: int = 0
    skipped_no_history: int = 0


def _training_matches(
    session: Session, now: datetime, league_id: int
) -> tuple[list[MatchResult], list[int]]:
    """Finished matches before ``now`` and their fixture ids."""
    stmt = select(Fixture).where(
        Fixture.league_id == league_id,
        Fixture.status == FixtureStatus.FINISHED.value,
        Fixture.kickoff_at < now,
        Fixture.home_score.is_not(None),
        Fixture.away_score.is_not(None),
    )
    fixtures = session.scalars(stmt).unique().all()
    matches = [
        MatchResult(
            home=str(f.home_team_id),
            away=str(f.away_team_id),
            home_goals=f.home_score,  # type: ignore[arg-type]
            away_goals=f.away_score,  # type: ignore[arg-type]
            kickoff_at=f.kickoff_at,
            season=f.season,
        )
        for f in fixtures
    ]
    return matches, [f.id for f in fixtures]


def _results_provenance(
    session: Session, matches: list[MatchResult], fixture_ids: list[int]
) -> dict[str, object]:
    """When the training results became known: the latest kickoff (what
    ``input_data_as_of`` uses) and the latest time a result was first stored
    (fixture_observations), plus how many results have no observation."""
    observed = queries.result_first_observed(session, fixture_ids)
    return {
        "results_count": len(matches),
        "results_kickoff_until": max(m.kickoff_at for m in matches).isoformat(),
        "results_observed_until": max(observed.values()).isoformat() if observed else None,
        "results_without_observation": len(fixture_ids) - len(observed),
    }


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
    template = model or PoissonEloModel()
    model_version = get_or_create_model_version(session, template)

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
    by_league: dict[int, list[Fixture]] = defaultdict(list)
    for fixture in upcoming:
        by_league[fixture.league_id].append(fixture)

    candidates = created = skipped_no_odds = skipped_cup = skipped_history = leagues = 0
    for league_id, fixtures in by_league.items():
        candidates += len(fixtures)
        league = session.get(League, league_id)
        if league is None or league.type == LeagueType.CUP.value:
            skipped_cup += len(fixtures)
            continue
        snapshots = {f.id: _latest_snapshot(session, f, bookmaker, now) for f in fixtures}
        with_odds = [f for f in fixtures if snapshots[f.id] is not None]
        skipped_no_odds += len(fixtures) - len(with_odds)
        if not with_odds:
            continue
        matches, match_ids = (
            _training_matches(session, now, league_id) if league.results_synced_at else ([], [])
        )
        if len(matches) < MIN_TRAINING_MATCHES:
            skipped_history += len(with_odds)
            continue
        fitted = PoissonEloModel(
            params=replace(template.params), calibrator=template.calibrator
        ).fit(matches, as_of=now)
        results_as_of = max(m.kickoff_at for m in matches)
        provenance = _results_provenance(session, matches, match_ids)
        leagues += 1
        for fixture in with_odds:
            snapshot = snapshots[fixture.id]
            assert snapshot is not None
            out = fitted.predict(str(fixture.home_team_id), str(fixture.away_team_id))
            # Deterministic "as of": the newest input timestamp, NOT wall-clock time,
            # so identical inputs always map to the same idempotency key.
            input_as_of = max(snapshot.captured_at, results_as_of)
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
                    features={**out.features, **provenance},
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
        unchanged=candidates - created - skipped_no_odds - skipped_cup - skipped_history,
        skipped_no_odds=skipped_no_odds,
        leagues_predicted=leagues,
        skipped_cup=skipped_cup,
        skipped_no_history=skipped_history,
    )
    logger.info("prediction job finished %s", result)
    return result
