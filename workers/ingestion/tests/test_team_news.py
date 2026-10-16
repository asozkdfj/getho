"""Team news: absences, official line-ups and player minutes (mock + API-Football fake)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.config import Settings
from edge_api.db.models import Fixture, PlayerAppearance, TeamNewsSnapshot
from edge_ingestion.jobs import run_ingestion
from edge_ingestion.providers import ApiFootballProvider, MockProvider
from edge_ingestion.providers.mock import LINEUPS_KNOWN
from edge_ingestion.team_news import content_hash, ingest_team_news
from edge_ingestion.testing import REF, FakeApiFootball

ALL = Settings(team_news_leagues="all", appearances_per_run=10_000)


def _count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where))


def test_mock_team_sheets_are_deterministic_and_complete():
    p = MockProvider(REF)
    fixtures = p.get_fixtures(REF - timedelta(days=3), REF + timedelta(days=3))
    finished = [f.provider_id for f in fixtures if f.status == "finished"]
    lineups = p.get_lineups(finished)
    assert lineups == MockProvider(REF).get_lineups(finished)
    assert all(len(lu.starters) == 11 for lu in lineups)
    assert all(len({s.provider_id for s in lu.starters}) == 11 for lu in lineups)
    minutes = {}
    for ap in p.get_appearances(finished):
        key = (ap.fixture_provider_id, ap.team_provider_id)
        minutes[key] = minutes.get(key, 0) + ap.minutes
    assert minutes and set(minutes.values()) == {990}  # 11 players x 90 minutes


def test_lineups_only_appear_shortly_before_kickoff():
    p = MockProvider(REF)
    upcoming = [f for f in p.get_fixtures(REF, REF + timedelta(days=3)) if f.status == "scheduled"]
    f = upcoming[0]
    assert p.get_lineups([f.provider_id]) == []
    just_before = MockProvider(f.kickoff_at - LINEUPS_KNOWN + timedelta(minutes=1))
    assert len(just_before.get_lineups([f.provider_id])) == 2


def test_team_news_ingestion_is_idempotent_and_append_only(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    first = ingest_team_news(db_session, provider, now=now, settings=ALL)
    db_session.commit()
    assert first.absence_snapshots > 0 and first.appearances_inserted > 0
    counts = (_count(db_session, TeamNewsSnapshot), _count(db_session, PlayerAppearance))
    again = ingest_team_news(db_session, MockProvider(now), now=now, settings=ALL)
    db_session.commit()
    assert (again.absence_snapshots, again.lineup_snapshots) == (0, 0)
    assert (_count(db_session, TeamNewsSnapshot), _count(db_session, PlayerAppearance)) == counts
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(text("UPDATE team_news_snapshots SET kind = 'x'"))
    db_session.rollback()


def test_lineups_are_stored_once_published(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    db_session.commit()
    f = db_session.scalars(
        select(Fixture)
        .where(Fixture.status == "scheduled", Fixture.kickoff_at > now)
        .order_by(Fixture.kickoff_at)
    ).first()
    before = f.kickoff_at - timedelta(minutes=30)
    res = ingest_team_news(
        db_session, MockProvider(before), now=before, settings=ALL, lineups_only=True
    )
    db_session.commit()
    assert res.lineup_snapshots >= 2
    snaps = db_session.scalars(
        select(TeamNewsSnapshot).where(
            TeamNewsSnapshot.fixture_id == f.id, TeamNewsSnapshot.kind == "lineup"
        )
    ).all()
    assert len(snaps) == 2 and all(len(s.payload["starters"]) == 11 for s in snaps)
    assert all(s.content_hash == content_hash(s.payload) for s in snaps)
    later = before + timedelta(minutes=10)  # polled again: nothing new
    res = ingest_team_news(
        db_session, MockProvider(later), now=later, settings=ALL, lineups_only=True
    )
    assert res.lineup_snapshots == 0


def test_scope_limits_team_news_to_chosen_leagues(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    ingest_team_news(db_session, provider, now=now, settings=Settings(team_news_leagues="kor-1"))
    db_session.commit()
    leagues = set(
        db_session.scalars(
            select(Fixture.league_id)
            .join(TeamNewsSnapshot, TeamNewsSnapshot.fixture_id == Fixture.id)
            .distinct()
        )
    ) | set(
        db_session.scalars(
            select(Fixture.league_id)
            .join(PlayerAppearance, PlayerAppearance.fixture_id == Fixture.id)
            .distinct()
        )
    )
    assert len(leagues) == 1


def _api(fake):
    return ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )


def test_api_football_team_news_parsing():
    fake = FakeApiFootball()
    p = _api(fake)
    p.get_leagues()
    upcoming = {
        f.provider_id: f.kickoff_at
        for f in p.get_fixtures(REF, REF + timedelta(days=5))
        if f.status == "scheduled"
    }
    assert upcoming
    absences = p.get_absences(upcoming)
    assert absences and {a.status for a in absences} == {"out"}
    assert all(a.reason == "Hamstring Injury" for a in absences)
    finished = [
        f.provider_id
        for f in p.get_fixtures(REF - timedelta(days=3), REF)
        if f.status == "finished"
    ]
    fake.calls.clear()
    apps = p.get_appearances(finished)
    assert len(fake.calls) == -(-len(finished) // 20)  # batched: 20 fixtures per request
    assert apps and all(a.minutes == 90 and a.started for a in apps)  # unused subs skipped
    lineups = p.get_lineups(finished)
    assert lineups and all(len(lu.starters) == 11 for lu in lineups)
    assert all(lu.formation == "4-3-3" for lu in lineups)


def test_lineup_backtest_runs_on_collected_player_minutes(db_session, now):
    """The `--source db` path end to end on mock data (a code check, not evidence)."""
    from edge_ingestion.lineup_backtest import evaluate_split, load_db_matches
    from edge_ingestion.team_news import ingest_appearances
    from edge_ml.model import ModelParams

    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    ingest_appearances(
        db_session, provider, now=now, scope=None, limit=10_000, lookback=timedelta(days=420)
    )
    db_session.commit()
    data, names = load_db_matches(db_session, "mock", min_matches=200)
    assert {"eng-1", "esp-1"} <= set(data)
    m = data["eng-1"][0]
    assert len(m.lineups.home.starters) == 11 and sum(m.lineups.home.minutes.values()) == 990
    res = evaluate_split({"eng-1": data["eng-1"]}, names, ModelParams(), 0.6)
    assert set(res["test"]["models"]) == {"base_rate", "production", "production_lineup"}
    assert res["test"]["n_matches"] > 50
