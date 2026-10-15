from datetime import timedelta

from sqlalchemy import func, select

from edge_api.db.models import Fixture, OddsSnapshot, Team
from edge_ingestion.jobs import run_ingestion
from edge_ingestion.providers import MockProvider


def _counts(session):
    return tuple(
        session.scalar(select(func.count()).select_from(m)) for m in (Team, Fixture, OddsSnapshot)
    )


def test_ingestion_is_idempotent(db_session, now):
    first = run_ingestion(db_session, MockProvider(now), now=now)
    db_session.commit()
    counts = _counts(db_session)
    assert first.teams_changed == 20
    assert first.fixtures_changed == counts[1] > 0
    assert first.odds_inserted == counts[2] > 0

    second = run_ingestion(db_session, MockProvider(now), now=now)
    db_session.commit()
    assert (second.teams_changed, second.fixtures_changed, second.odds_inserted) == (0, 0, 0)
    assert _counts(db_session) == counts


def test_timestamps_are_stored_in_utc(db_session, now):
    run_ingestion(db_session, MockProvider(now), now=now)
    db_session.commit()
    f = db_session.scalars(select(Fixture).limit(1)).first()
    assert f.kickoff_at.utcoffset() == timedelta(0)


def test_later_run_appends_snapshots_and_updates_results(db_session, now):
    run_ingestion(db_session, MockProvider(now), now=now)
    db_session.commit()
    before = {o.id: (o.odds_home, o.captured_at) for o in db_session.scalars(select(OddsSnapshot))}
    finished_before = db_session.scalar(
        select(func.count()).select_from(Fixture).where(Fixture.status == "finished")
    )

    later = now + timedelta(hours=12)  # same 4-day grid window, time moved on
    result = run_ingestion(db_session, MockProvider(later), now=later)
    db_session.commit()

    assert result.odds_inserted > 0  # new snapshots appended ...
    after = {o.id: (o.odds_home, o.captured_at) for o in db_session.scalars(select(OddsSnapshot))}
    assert {k: after[k] for k in before} == before  # ... old ones untouched
    finished_after = db_session.scalar(
        select(func.count()).select_from(Fixture).where(Fixture.status == "finished")
    )
    assert finished_after > finished_before
    # status/score updates (plus fixtures that newly entered the look-ahead window)
    assert result.fixtures_changed >= finished_after - finished_before
