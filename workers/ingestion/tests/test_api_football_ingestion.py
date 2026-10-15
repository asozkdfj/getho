"""End-to-end: API-Football payloads -> DB -> predictions (offline, fake transport)."""

from sqlalchemy import func, select

from edge_api.db.models import Fixture, OddsSnapshot, Prediction, Team
from edge_ingestion.jobs import run_pipeline
from edge_ingestion.providers import ApiFootballProvider
from edge_ingestion.testing import REF, FakeApiFootball


def _provider(fake):
    return ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_pipeline_with_api_football_is_idempotent(db_session):
    fake = FakeApiFootball()
    first = run_pipeline(db_session, _provider(fake), now=REF, bookmaker="bet365")
    db_session.commit()
    assert first.ingestion.teams_changed == 21
    assert first.ingestion.odds_inserted > 0
    assert first.predictions.created > 0
    assert len(fake.calls) <= 8  # teams x2 + fixtures x2 + odds pages: fits the free quota

    counts = [_count(db_session, m) for m in (Team, Fixture, OddsSnapshot, Prediction)]
    again = run_pipeline(db_session, _provider(FakeApiFootball()), now=REF, bookmaker="bet365")
    db_session.commit()
    assert again.ingestion.odds_inserted == 0 and again.predictions.created == 0
    assert [_count(db_session, m) for m in (Team, Fixture, OddsSnapshot, Prediction)] == counts


def test_refreshed_odds_append_new_snapshots(db_session):
    run_pipeline(db_session, _provider(FakeApiFootball()), now=REF, bookmaker="bet365")
    db_session.commit()
    before = _count(db_session, OddsSnapshot)
    later = FakeApiFootball(odds_update="2026-10-15T08:59:00+00:00")  # provider refreshed prices
    res = run_pipeline(db_session, _provider(later), now=REF, bookmaker="bet365")
    db_session.commit()
    assert res.ingestion.odds_inserted == before  # one new snapshot per (fixture, bookmaker)
    assert res.predictions.created > 0  # new market input -> new prediction rows


def test_mock_and_real_provider_data_are_not_mixed(db_session):
    from edge_ingestion.providers import MockProvider

    run_pipeline(db_session, MockProvider(REF), now=REF, bookmaker="mockbook")
    run_pipeline(db_session, _provider(FakeApiFootball()), now=REF, bookmaker="bet365")
    db_session.commit()
    mixed = db_session.scalar(
        select(func.count())
        .select_from(Prediction)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .join(OddsSnapshot, OddsSnapshot.id == Prediction.market_odds_snapshot_id)
        .where(
            (Fixture.provider == "api_football") & (OddsSnapshot.bookmaker == "mockbook")
            | (Fixture.provider == "mock") & (OddsSnapshot.bookmaker == "bet365")
        )
    )
    assert mixed == 0
    real = db_session.scalars(
        select(Prediction)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .where(Fixture.provider == "api_football")
    ).all()
    assert real
    api_results = db_session.scalar(
        select(func.count())
        .select_from(Fixture)
        .where(Fixture.provider == "api_football", Fixture.status == "finished")
    )
    for p in real:
        # trained only on api_football results, not on the synthetic mock history
        assert p.features["training_matches"] == api_results
