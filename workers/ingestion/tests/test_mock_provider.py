from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from edge_ingestion.providers import MockProvider, get_provider
from edge_ingestion.providers.base import FootballDataProvider
from edge_ingestion.providers.mock import LEAGUES, SNAPSHOT_OFFSETS, _round_robin
from edge_ml.market import overround

REF = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
ALL = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))


def test_factory_and_interface():
    assert isinstance(get_provider("mock"), FootballDataProvider)
    with pytest.raises(ValueError):
        get_provider("does-not-exist")


def test_rejects_naive_reference_time():
    with pytest.raises(ValueError):
        MockProvider(reference_time=datetime(2026, 1, 1))  # noqa: DTZ001


def test_round_robin_is_complete_double_round_robin():
    codes = [f"T{i}" for i in range(20)]
    rounds = _round_robin(codes)
    assert len(rounds) == 38
    for rnd in rounds:
        teams = [t for pair in rnd for t in pair]
        assert sorted(teams) == sorted(codes)  # everybody plays exactly once per round
    pairs = Counter(pair for rnd in rounds for pair in rnd)
    assert len(pairs) == 20 * 19 and set(pairs.values()) == {1}  # each ordered pair once


def test_provider_is_deterministic():
    a, b = MockProvider(REF), MockProvider(REF)
    fa, fb = a.get_fixtures(*ALL), b.get_fixtures(*ALL)
    assert fa == fb
    ids = [f.provider_id for f in fa]
    assert a.get_odds(ids) == b.get_odds(ids)


def test_same_grid_window_gives_identical_data():
    later_same_window = REF + timedelta(minutes=1)
    a, b = MockProvider(REF), MockProvider(later_same_window)
    assert a.season_start == b.season_start


def test_catalogue_has_leagues_and_a_cup():
    leagues = {lg.provider_id: lg for lg in MockProvider(REF).get_leagues()}
    assert set(leagues) == {"eng-1", "esp-1", "kor-1", "eng-cup"}
    assert leagues["eng-cup"].type == "cup" and leagues["eng-1"].type == "league"
    assert leagues["kor-1"].season == "2026"  # calendar-year season
    assert leagues["eng-1"].season == "2026-27"
    assert all(lg.has_odds for lg in leagues.values())


def test_team_ids_are_unique_across_leagues():
    codes = [t.code for lg in LEAGUES if lg.type == "league" for t in lg.teams]
    assert len(codes) == len(set(codes))


def test_league_history_is_two_full_seasons():
    p = MockProvider(REF)
    sizes = {lg.provider_id: len(p.get_league_history(lg)) for lg in p.get_leagues()}
    assert sizes["eng-1"] == sizes["esp-1"] == 2 * 380
    assert sizes["kor-1"] == 2 * 132
    ids = [f.provider_id for lg in p.get_leagues() for f in p.get_league_history(lg)]
    assert len(ids) == len(set(ids))


def test_premier_league_fixture_ids_are_unchanged():
    # data collected before the multi-league version keeps matching (upsert, no duplicates)
    epl = [f for f in MockProvider(REF).get_fixtures(*ALL) if f.league_provider_id == "eng-1"]
    assert all(f.provider_id.startswith(("2025-26-r", "2026-27-r")) for f in epl)


def test_fixture_status_is_consistent_with_reference_time():
    p = MockProvider(REF)
    fixtures = [f for f in p.get_fixtures(*ALL) if f.league_provider_id == "eng-1"]
    assert len(fixtures) == 2 * 380
    for f in fixtures:
        assert f.kickoff_at.tzinfo is not None
        if f.status == "finished":
            assert f.kickoff_at + timedelta(hours=2) <= REF
            assert f.home_score is not None and f.away_score is not None
        else:
            assert f.home_score is None and f.away_score is None
        if f.status == "scheduled":
            assert f.kickoff_at > REF
    statuses = Counter(f.status for f in fixtures)
    assert statuses["finished"] > 380 and statuses["scheduled"] > 0


def test_there_are_fixtures_today_and_this_week():
    fixtures = MockProvider(REF).get_fixtures(REF, REF + timedelta(days=7))
    assert len(fixtures) >= 10


def test_odds_are_valid_and_never_from_the_future():
    p = MockProvider(REF)
    fixtures = p.get_fixtures(REF - timedelta(days=30), REF + timedelta(days=14))
    odds = p.get_odds([f.provider_id for f in fixtures])
    assert odds
    kickoff = {f.provider_id: f.kickoff_at for f in fixtures}
    for o in odds:
        assert o.captured_at <= REF
        assert o.captured_at < kickoff[o.fixture_provider_id]
        assert min(o.odds_home, o.odds_draw, o.odds_away) > 1.0
        assert 0.02 < overround((o.odds_home, o.odds_draw, o.odds_away)) < 0.08
    per_fixture = Counter(o.fixture_provider_id for o in odds)
    assert max(per_fixture.values()) == len(SNAPSHOT_OFFSETS)
