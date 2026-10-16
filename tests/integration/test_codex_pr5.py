"""PR #5 boundary regressions. Run with PR #5 packages on PYTHONPATH."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from edge_api.config import Settings
from edge_api.db.models import DailyPickEvent, Fixture, IngestionRun, TeamNewsSnapshot
from edge_api.services.picks import publish_daily_pick, settle_daily_picks
from edge_ingestion import jobs
from edge_ingestion.providers import MockProvider
from edge_ingestion.providers.http import ProviderError
from tests.integration.test_picks import _pick_time, settings

pytestmark = pytest.mark.skipif(
    not hasattr(jobs, "reconcile_overdue_fixtures"), reason="requires PR #5 implementation"
)


@pytest.mark.parametrize("status", ["scheduled", "live", "finished"])
def test_moved_pick_is_void_even_when_first_refresh_is_live_or_finished(
    session_factory, seeded, now, status
):
    with session_factory() as session:
        decision, _ = _pick_time(session, now)
        pick = publish_daily_pick(session, settings(), decision)
        fixture = pick.fixture
        fixture.kickoff_at += timedelta(days=3)
        fixture.status = status
        if status == "finished":
            fixture.home_score, fixture.away_score = 2, 1
        session.flush()
        result = settle_daily_picks(session, settings(), fixture.kickoff_at + timedelta(hours=3))
        assert result["voided"] == 1 and result["settled"] == 0, result
        event = session.scalars(select(DailyPickEvent)).one()
        assert event.reason == "fixture rescheduled"


@pytest.mark.parametrize("capacity", [1, 100])
def test_unresolvable_newest_fixture_does_not_starve_older_pending_fixture(
    db_session, now, capacity
):
    provider = MockProvider(now)
    jobs.run_ingestion(db_session, provider, now=now)
    base = db_session.scalars(
        select(Fixture)
        .where(Fixture.status == "scheduled", Fixture.kickoff_at > now)
        .order_by(Fixture.kickoff_at)
        .limit(1)
    ).one()
    fixtures = []
    for i in range(capacity + 1):
        fixture = Fixture(
            provider="mock",
            provider_id=f"qa-overdue-{i}",
            league_id=base.league_id,
            season=base.season,
            round=base.round,
            home_team_id=base.home_team_id,
            away_team_id=base.away_team_id,
            kickoff_at=now - timedelta(hours=5 + i),
            status="scheduled",
        )
        db_session.add(fixture)
        fixtures.append(fixture)
    db_session.flush()
    asked = []

    def unresolved(ids):
        asked.extend(ids)
        return []

    provider.get_fixtures_by_ids = unresolved
    for _ in range(2):
        jobs.reconcile_overdue_fixtures(db_session, provider, now=now, seen=set(), limit=capacity)
    assert fixtures[-1].provider_id in asked, f"Same newest rows consumed both batches: {asked}"


@pytest.mark.parametrize("error_type", [ProviderError, RuntimeError])
def test_partial_news_write_is_rolled_back_and_only_provider_errors_are_isolated(
    db_session, now, monkeypatch, error_type
):
    def partial_news(session, provider, **kwargs):
        fixture = session.scalars(select(Fixture).limit(1)).one()
        session.add(
            TeamNewsSnapshot(
                fixture_id=fixture.id,
                team_id=fixture.home_team_id,
                provider="mock",
                kind="absences",
                payload={"qa": "partial-write"},
                content_hash="a" * 64,
                captured_at=now,
            )
        )
        session.flush()
        assert session.scalar(select(func.count()).select_from(TeamNewsSnapshot)) == 1
        raise error_type("QA after a flushed partial news write")

    monkeypatch.setattr(jobs, "ingest_team_news", partial_news)
    config = Settings(data_provider="mock")
    if error_type is ProviderError:
        result = jobs.run_pipeline(
            db_session, MockProvider(now), now=now, bookmaker="mockbook", settings=config
        )
        db_session.commit()
        assert result.predictions.created > 0 and "error" in result.team_news
        assert db_session.scalar(select(func.count()).select_from(TeamNewsSnapshot)) == 0
        assert db_session.scalars(select(IngestionRun)).one().status == "success"
    else:
        with pytest.raises(RuntimeError):
            jobs.run_pipeline(
                db_session, MockProvider(now), now=now, bookmaker="mockbook", settings=config
            )
        db_session.rollback()
        assert db_session.scalar(select(func.count()).select_from(Fixture)) == 0
