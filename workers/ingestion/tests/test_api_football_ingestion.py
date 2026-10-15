"""End-to-end: API-Football payloads -> DB -> predictions (offline, fake transport)."""

from collections import Counter

from sqlalchemy import func, select

from edge_api.db.models import Fixture, League, OddsSnapshot, Prediction, Team
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
    assert first.ingestion.leagues_changed == 4
    assert first.ingestion.odds_inserted > 0
    assert first.predictions.created > 0
    # catalogue + 12 calendar days of fixtures + 2 leagues x 2 seasons history + odds pages
    paths = Counter(c[0] for c in fake.calls)
    assert paths["/leagues"] == 1 and paths["/fixtures"] == 12 + 4
    assert first.ingestion.requests == len(fake.calls) <= 30

    counts = [_count(db_session, m) for m in (Team, Fixture, OddsSnapshot, Prediction)]
    again = run_pipeline(db_session, _provider(FakeApiFootball()), now=REF, bookmaker="bet365")
    db_session.commit()
    assert again.ingestion.odds_inserted == 0 and again.predictions.created == 0
    assert [_count(db_session, m) for m in (Team, Fixture, OddsSnapshot, Prediction)] == counts


def test_leagues_cups_and_leagues_without_odds(db_session):
    res = run_pipeline(db_session, _provider(FakeApiFootball()), now=REF, bookmaker="bet365")
    db_session.commit()
    leagues = {lg.provider_id: lg for lg in db_session.scalars(select(League))}
    assert leagues["292"].current_season == "2026" and leagues["39"].current_season == "2026-27"
    assert leagues["45"].type == "cup" and leagues["45"].results_synced_at is None
    assert leagues["1000"].has_odds is False and leagues["1000"].results_synced_at is None
    predicted = set(
        db_session.scalars(
            select(League.provider_id)
            .join(Fixture, Fixture.league_id == League.id)
            .join(Prediction, Prediction.fixture_id == Fixture.id)
        )
    )
    assert predicted == {"39", "292"}  # never the cup
    assert res.predictions.skipped_cup > 0 and res.predictions.leagues_predicted == 2
    teams = {t.provider_id: t for t in db_session.scalars(select(Team))}
    assert teams["42"].logo_url == "t42.png"


def test_low_budget_postpones_backfill(db_session):
    fake = FakeApiFootball(remaining=100)  # below API_FOOTBALL_MIN_REMAINING
    res = run_pipeline(db_session, _provider(fake), now=REF, bookmaker="bet365")
    db_session.commit()
    assert res.ingestion.leagues_backfilled == 0 and res.ingestion.leagues_pending_backfill == 2
    assert res.ingestion.odds_inserted == 0 and res.predictions.created == 0
    assert not any(c[0] == "/odds" for c in fake.calls)


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
    epl_results = db_session.scalar(
        select(func.count())
        .select_from(Fixture)
        .join(League, League.id == Fixture.league_id)
        .where(
            Fixture.provider == "api_football",
            Fixture.status == "finished",
            League.provider_id == "39",
        )
    )
    assert 0 < epl_results < api_results
    for p in real:
        # trained only on its own league's api_football results (no mock, no other league)
        league = db_session.get(Fixture, p.fixture_id).league.provider_id
        if league == "39":
            assert p.features["training_matches"] == epl_results
