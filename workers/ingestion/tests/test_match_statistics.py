"""Post-match team statistics (shots, shots on target, xG): collected with player
minutes from one fetch, append-only, read as of a moment."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.config import Settings
from edge_api.db.models import Fixture, MatchStatistic, PlayerAppearance
from edge_api.services.queries import latest_statistics
from edge_ingestion.jobs import run_ingestion
from edge_ingestion.providers import ApiFootballProvider, MockProvider
from edge_ingestion.team_news import (
    _insert_statistics,
    _team_ids,
    ingest_post_match,
    ingest_team_news,
)
from edge_ingestion.testing import REF, FakeApiFootball

ALL = Settings(team_news_leagues="all", appearances_per_run=10_000)


def _count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where))


def test_statistics_are_stored_once_per_team_with_the_minutes(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    first = ingest_team_news(db_session, provider, now=now, settings=ALL)
    assert first.statistics_inserted > 0 and first.appearances_inserted > 0
    with_minutes = db_session.scalar(select(func.count(PlayerAppearance.fixture_id.distinct())))
    assert first.statistics_inserted == 2 * with_minutes  # both teams of each fixture
    rows = db_session.scalars(select(MatchStatistic)).all()
    assert all(r.source == "ingest" and r.expected_goals is not None for r in rows)
    assert all(r.expected_goals >= 0 and r.shots_on_target <= r.shots for r in rows)
    again = ingest_team_news(db_session, MockProvider(now), now=now, settings=ALL)
    assert again.statistics_inserted == 0 and again.appearances_inserted == 0


def test_a_changed_report_is_a_new_row_and_reads_as_of_see_the_old_one(db_session, now):
    from conftest import set_test_wall_clock

    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    ingest_team_news(db_session, provider, now=now, settings=ALL)
    fid = db_session.scalars(select(MatchStatistic.fixture_id).limit(1)).one()
    before = {(r.team_id, r.expected_goals) for r in latest_statistics(db_session, [fid])}

    original = provider.get_match_statistics
    provider.get_match_statistics = lambda ids: [
        replace(s, expected_goals=(s.expected_goals or 0) + 0.5) for s in original(ids)
    ]
    later = now + timedelta(days=1)
    set_test_wall_clock(db_session, later)
    # the fixture already has minutes and statistics: a revision arrives via backfill
    pid = db_session.get(Fixture, fid).provider_id
    report = provider.get_post_match([pid])
    added = _insert_statistics(
        db_session, "mock", report, {pid: fid}, _team_ids(db_session, "mock"), "backfill"
    )
    assert added == 2
    now_rows = {(r.team_id, r.expected_goals) for r in latest_statistics(db_session, [fid])}
    assert now_rows != before
    as_of = {(r.team_id, r.expected_goals) for r in latest_statistics(db_session, [fid], now)}
    assert as_of == before  # a decision before the revision saw the first report


def test_fixtures_with_minutes_but_no_statistics_are_completed(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    original = provider.get_match_statistics
    provider.get_match_statistics = lambda ids: []  # e.g. collected before this table
    ingest_team_news(db_session, provider, now=now, settings=ALL)
    assert _count(db_session, MatchStatistic) == 0 and _count(db_session, PlayerAppearance) > 0
    provider.get_match_statistics = original
    appearances, statistics = ingest_post_match(
        db_session, provider, now=now, scope=None, limit=10_000
    )
    assert appearances == 0 and statistics > 0


def test_a_team_whose_statistics_are_missing_is_retried(db_session, now):
    """One team's row stored must not end the retry for the other (Codex STAT-1)."""
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    original = provider.get_match_statistics

    def home_only(ids):
        seen: set[str] = set()
        out = []
        for row in original(ids):
            if row.fixture_provider_id not in seen:
                seen.add(row.fixture_provider_id)
                out.append(row)
        return out

    provider.get_match_statistics = home_only
    appearances, first = ingest_post_match(db_session, provider, now=now, scope=None, limit=10_000)
    assert appearances > 0 and first > 0
    provider.get_match_statistics = original
    _, repaired = ingest_post_match(db_session, provider, now=now, scope=None, limit=10_000)
    assert repaired == first  # the other team of every fixture, nothing duplicated
    _, again = ingest_post_match(db_session, provider, now=now, scope=None, limit=10_000)
    assert again == 0


def test_api_football_reads_minutes_and_statistics_from_one_fetch():
    fake = FakeApiFootball()
    p = ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )
    p.get_leagues()
    finished = [
        f.provider_id
        for f in p.get_fixtures(REF - timedelta(days=7), REF)
        if f.status == "finished"
    ]
    fake.calls.clear()
    report = p.get_post_match(finished)
    assert len(fake.calls) == -(-len(finished) // 20)  # the same requests as minutes alone
    assert report.appearances and report.statistics
    assert {s.fixture_provider_id for s in report.statistics} <= set(finished)


def test_backfilled_statistics_are_marked_and_rows_are_append_only(session_factory, now):
    with session_factory() as s:
        provider = MockProvider(now)
        run_ingestion(s, provider, now=now)
        _, statistics = ingest_post_match(
            s, provider, now=now, scope=None, limit=10_000, source="backfill"
        )
        assert statistics > 0
        assert _count(s, MatchStatistic, MatchStatistic.source != "backfill") == 0
        s.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE match_statistics SET expected_goals = 9"))
