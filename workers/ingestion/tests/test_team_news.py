"""Team news: absences, official line-ups and player minutes (mock + API-Football fake)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.config import Settings
from edge_api.db.models import Fixture, PlayerAppearance, Team, TeamNewsSnapshot
from edge_ingestion.jobs import run_ingestion
from edge_ingestion.providers import ApiFootballProvider, MockProvider
from edge_ingestion.providers.base import AbsenceReport
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


# ------------------------------------------- absences: reported / none / unknown
def _absence_states(session):
    snaps = session.scalars(
        select(TeamNewsSnapshot).where(TeamNewsSnapshot.kind == "absences")
    ).all()
    return {(s.fixture_id, s.team_id): s.payload["players"] for s in snaps}


def test_checked_teams_without_absences_get_an_empty_snapshot(db_session, now):
    from edge_ingestion.providers.mock import ABSENCES_KNOWN

    wide = Settings(team_news_leagues="all", absences_horizon_hours=24 * 5)
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    ingest_team_news(db_session, provider, now=now, settings=wide)
    states = _absence_states(db_session)
    covered = db_session.scalars(
        select(Fixture).where(
            Fixture.status == "scheduled",
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= now + ABSENCES_KNOWN,
        )
    ).all()
    assert covered
    for f in covered:  # both teams checked: players listed, or an empty list
        assert (f.id, f.home_team_id) in states and (f.id, f.away_team_id) in states
    assert any(players == [] for players in states.values())
    later = db_session.scalars(
        select(Fixture.id).where(
            Fixture.kickoff_at > now + ABSENCES_KNOWN + timedelta(hours=1),
            Fixture.kickoff_at <= now + timedelta(hours=wide.absences_horizon_hours),
        )
    ).all()
    # not yet covered by the provider: no snapshot at all (unknown), never "none"
    assert later and not any(fid in later for fid, _ in states)


def test_no_empty_snapshot_for_a_league_without_injury_coverage(db_session, now):
    from edge_api.db.models import League

    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    db_session.execute(League.__table__.update().values(has_injuries=False))
    ingest_team_news(db_session, provider, now=now, settings=ALL)
    states = _absence_states(db_session)
    assert states and all(players for players in states.values())


def test_api_football_covers_only_the_days_it_fetched():
    fake = FakeApiFootball()
    p = _api(fake)
    leagues = p.get_leagues()
    assert all(lg.has_injuries for lg in leagues)
    upcoming = {
        f.provider_id: f.kickoff_at
        for f in p.get_fixtures(REF, REF + timedelta(days=5))
        if f.status == "scheduled"
    }
    days = {k.date() for k in upcoming.values()}
    assert len(days) >= 2
    report = p.get_absence_report(upcoming)
    assert report.covered == frozenset(upcoming)
    p.budget_ok = lambda: False  # budget used up: nothing fetched, nothing covered
    assert p.get_absence_report(upcoming).covered == frozenset()


def test_a_report_that_returns_to_an_earlier_state_is_stored_again(db_session, now):
    """absent -> fit -> absent: the third report equals the first and must still
    become the latest (content-hash dedup used to drop it)."""
    from edge_ingestion.providers.base import AbsenceReport

    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    full = provider.get_absence_report
    ingest_team_news(db_session, provider, now=now, settings=ALL)
    fid, tid = next((k for k, players in _absence_states(db_session).items() if players))
    fixture_pid = db_session.get(Fixture, fid).provider_id
    team_pid = db_session.get(Team, tid).provider_id

    def fit(fixtures):  # the same report, with that team's absentees fit again
        r = full(fixtures)
        keep = [
            a
            for a in r.absences
            if (a.fixture_provider_id, a.team_provider_id) != (fixture_pid, team_pid)
        ]
        return AbsenceReport(keep, r.covered)

    provider.get_absence_report = fit
    ingest_team_news(db_session, provider, now=now + timedelta(minutes=10), settings=ALL)
    provider.get_absence_report = full
    ingest_team_news(db_session, provider, now=now + timedelta(minutes=20), settings=ALL)
    history = db_session.scalars(
        select(TeamNewsSnapshot)
        .where(
            TeamNewsSnapshot.kind == "absences",
            TeamNewsSnapshot.fixture_id == fid,
            TeamNewsSnapshot.team_id == tid,
        )
        .order_by(TeamNewsSnapshot.captured_at)
    ).all()
    assert [bool(s.payload["players"]) for s in history] == [True, False, True]
    assert history[0].content_hash == history[2].content_hash


def _injuries(p, monkeypatch, rows):
    monkeypatch.setattr(p, "budget_ok", lambda: True)
    monkeypatch.setattr(p, "_get", lambda *args, **kwargs: {"response": rows})


def _row(fixture, team, player=True):
    item = {"fixture": {"id": fixture}, "team": {"id": team}, "player": {"type": "Missing Fixture"}}
    if player:
        item["player"].update({"id": 7, "name": "Somebody", "reason": "Injury"})
    return item


def test_malformed_injury_rows_leave_their_fixture_unknown(monkeypatch):
    """Codex QA MORN-2: an unreadable row is not "checked, none". Its fixture is
    not covered and keeps nothing (a partial list would replace the last good
    report); other fixtures of the day stay covered."""
    p = _api(FakeApiFootball())
    day = REF + timedelta(hours=1)
    wanted = {"123": day, "124": day, "125": day}
    _injuries(p, monkeypatch, [_row(123, 456), _row(123, 456, player=False), _row(124, 9)])
    report = p.get_absence_report(wanted)
    assert report.covered == frozenset({"124", "125"})  # 125: checked, nobody listed
    assert [a.fixture_provider_id for a in report.absences] == ["124"]

    _injuries(p, monkeypatch, [])  # a well-formed empty answer: every fixture checked
    assert p.get_absence_report(wanted).covered == frozenset(wanted)

    _injuries(p, monkeypatch, [{"team": {"id": 1}, "player": {"id": 2, "name": "x"}}])
    assert p.get_absence_report(wanted) == AbsenceReport([], frozenset())  # whole day unknown
