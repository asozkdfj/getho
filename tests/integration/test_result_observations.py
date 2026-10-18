"""When each result was first known, and corrections (fixture_observations)."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.db.models import Fixture, FixtureObservation, Prediction
from edge_api.services import queries
from edge_ingestion.jobs import ingest_fixtures, run_ingestion
from edge_ingestion.providers import MockProvider


def _count(s, *where):
    return s.scalar(select(func.count()).select_from(FixtureObservation).where(*where))


def _scheduled(provider, now):
    return next(
        f for f in provider.get_fixtures(now, now + timedelta(days=3)) if f.status == "scheduled"
    )


def test_every_stored_fixture_is_observed_once_and_a_rerun_adds_nothing(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    fixtures = db_session.scalar(select(func.count()).select_from(Fixture))
    assert _count(db_session) == fixtures
    assert _count(db_session, FixtureObservation.source != "ingest") == 0
    run_ingestion(db_session, MockProvider(now), now=now)
    assert _count(db_session) == fixtures


def test_a_result_and_its_correction_are_both_kept(db_session, now):
    from conftest import set_test_wall_clock

    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    base = _scheduled(provider, now)
    fid = db_session.scalar(select(Fixture.id).where(Fixture.provider_id == base.provider_id))

    finished_at = now + timedelta(hours=6)
    set_test_wall_clock(db_session, finished_at)
    ingest_fixtures(
        db_session, "mock", [replace(base, status="finished", home_score=2, away_score=1)]
    )
    assert queries.result_first_observed(db_session, [fid]) == {fid: finished_at}

    set_test_wall_clock(db_session, now + timedelta(days=1))
    ingest_fixtures(
        db_session, "mock", [replace(base, status="finished", home_score=2, away_score=2)]
    )
    # the first time a result was known does not move with the correction
    assert queries.result_first_observed(db_session, [fid]) == {fid: finished_at}
    history = queries.result_history(db_session, fid)
    assert [(h["status"], h["home_score"], h["away_score"]) for h in history] == [
        ("scheduled", None, None),
        ("finished", 2, 1),
        ("finished", 2, 2),
    ]
    assert [h["corrects_result"] for h in history] == [False, False, True]
    db_session.refresh(db_session.get(Fixture, fid))
    assert db_session.get(Fixture, fid).away_score == 2  # fixtures keeps the latest


def test_a_change_that_is_not_status_kickoff_or_score_is_not_an_observation(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    base = _scheduled(provider, now)
    before = _count(db_session)
    _, changed = ingest_fixtures(db_session, "mock", [replace(base, round=(base.round or 0) + 1)])
    assert changed == 1 and _count(db_session) == before
    ingest_fixtures(
        db_session, "mock", [replace(base, kickoff_at=base.kickoff_at + timedelta(days=2))]
    )
    assert _count(db_session) == before + 1  # a reschedule is


def test_observations_are_append_only(session_factory, now):
    with session_factory() as s:
        run_ingestion(s, MockProvider(now), now=now)
        s.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE fixture_observations SET home_score = 9"))
        s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM fixture_observations"))


def test_predictions_record_when_their_training_results_were_known(db_session, seeded, now):
    for p in db_session.scalars(select(Prediction)).all():
        f = p.features
        assert f["results_count"] >= 1 and f["results_without_observation"] == 0
        assert f["results_kickoff_until"] <= p.input_data_as_of.isoformat()
        assert f["results_observed_until"] is not None
        assert f["results_observed_until"] <= p.created_at.isoformat()


def test_migration_backfills_existing_fixtures_with_their_last_update(session_factory, seeded):
    """0008 on a database that already has fixtures: one 'backfill' row each,
    observed at the fixture's updated_at (never earlier than the truth)."""
    from alembic import command
    from alembic.config import Config

    from conftest import ROOT, TEST_DATABASE_URL, _install_test_clock

    cfg = Config(str(ROOT / "apps/api/alembic.ini"))
    cfg.attributes["url"] = TEST_DATABASE_URL
    with session_factory() as s:
        engine = s.get_bind()
    command.downgrade(cfg, "0007")
    try:
        command.upgrade(cfg, "0008")
    finally:
        command.upgrade(cfg, "head")
        _install_test_clock(engine)
    with session_factory() as s:
        fixtures = s.scalar(select(func.count()).select_from(Fixture))
        assert _count(s) == fixtures == _count(s, FixtureObservation.source == "backfill")
        mismatched = s.scalar(
            select(func.count())
            .select_from(FixtureObservation)
            .join(Fixture, Fixture.id == FixtureObservation.fixture_id)
            .where(
                (FixtureObservation.created_at != Fixture.updated_at)
                | FixtureObservation.status.is_distinct_from(Fixture.status)
                | FixtureObservation.home_score.is_distinct_from(Fixture.home_score)
            )
        )
        assert mismatched == 0
