"""Real-data pipeline failure paths: moved fixtures, optional team news failing,
rolled-back runs, bad provider rows (offline: mock provider / API-Football fake)."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from edge_api.config import Settings
from edge_api.db.models import (
    Fixture,
    IngestionRun,
    League,
    OddsSnapshot,
    Prediction,
    TeamNewsSnapshot,
)
from edge_ingestion.jobs import (
    INGEST_LOOKAHEAD,
    ingest_fixtures,
    ingest_odds,
    reconcile_overdue_fixtures,
    record_failed_run,
    run_ingestion,
    run_pipeline,
)
from edge_ingestion.providers import ApiFootballProvider, MockProvider
from edge_ingestion.providers.base import OddsData
from edge_ingestion.providers.http import ProviderError
from edge_ingestion.testing import REF, FakeApiFootball, envelope, json_response

NEWS = Settings(team_news_leagues="all", absences_horizon_hours=24 * 5, ingest_max_age_hours=10_000)


def _provider(fake):
    return ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )


def _count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where))


def _error(endpoint: str, n: int = 50):
    body = envelope(endpoint, {}, [], errors={"requests": "You have reached the request limit"})
    return [json_response(body) for _ in range(n)]


def _upcoming(session):
    return session.scalars(
        select(Fixture)
        .where(Fixture.status == "scheduled", Fixture.kickoff_at > REF)
        .order_by(Fixture.kickoff_at, Fixture.id)
    ).first()


# ------------------------------------------------- fixtures moved to another day
def test_overdue_fixture_moved_out_of_the_window_is_looked_up_by_id(db_session):
    run_ingestion(db_session, _provider(FakeApiFootball()), now=REF)
    f = _upcoming(db_session)
    real_kickoff = f.kickoff_at
    # as stored before the provider moved it: "scheduled" two days ago, and the
    # rolling window (which lists the new date) is not part of this call
    f.kickoff_at = REF - timedelta(days=2)
    db_session.flush()

    fake = FakeApiFootball()
    changed, unresolved = reconcile_overdue_fixtures(
        db_session, _provider(fake), now=REF, seen=set()
    )
    assert (changed, unresolved) == (1, 0)
    assert [c[1]["ids"] for c in fake.calls if "ids" in c[1]] == [f.provider_id]
    db_session.refresh(f)
    assert f.kickoff_at == real_kickoff and f.status == "scheduled"

    # fixtures the refreshed window already returned are not asked for again
    f.kickoff_at = REF - timedelta(days=2)
    db_session.flush()
    fake.calls.clear()
    reconcile_overdue_fixtures(db_session, _provider(fake), now=REF, seen={f.provider_id})
    assert not any("ids" in c[1] for c in fake.calls)


def test_overdue_fixture_the_provider_no_longer_returns_is_reported(db_session):
    run_ingestion(db_session, _provider(FakeApiFootball()), now=REF)
    f = _upcoming(db_session)
    f.kickoff_at = REF - timedelta(days=1)
    db_session.flush()
    fake = FakeApiFootball()
    fake.overrides["/fixtures"] = [json_response(envelope("fixtures", {}, []))]
    assert reconcile_overdue_fixtures(db_session, _provider(fake), now=REF, seen=set()) == (0, 1)
    db_session.refresh(f)
    assert f.status == "scheduled"  # left as is, never guessed


def test_overdue_lookup_waits_when_the_budget_is_low(db_session):
    run_ingestion(db_session, _provider(FakeApiFootball()), now=REF)
    f = _upcoming(db_session)
    f.kickoff_at = REF - timedelta(days=1)
    db_session.flush()
    fake = FakeApiFootball(remaining=100)
    provider = _provider(fake)
    provider.get_leagues()  # learn the remaining budget from a response header
    fake.calls.clear()
    assert reconcile_overdue_fixtures(db_session, provider, now=REF, seen=set()) == (0, 1)
    assert fake.calls == []


def test_old_and_finished_fixtures_are_not_reconciled(db_session):
    run_ingestion(db_session, _provider(FakeApiFootball()), now=REF)
    f = _upcoming(db_session)
    f.kickoff_at = REF - timedelta(days=60)  # beyond the lookback: not re-asked forever
    db_session.flush()
    fake = FakeApiFootball()
    assert reconcile_overdue_fixtures(db_session, _provider(fake), now=REF, seen=set()) == (0, 0)
    assert fake.calls == []


@pytest.mark.parametrize("capacity", [1, 100])
def test_unresolved_fixtures_do_not_starve_the_rest_of_the_backlog(db_session, now, capacity):
    """Codex QA F4: batches rotate, so fixtures the provider keeps not returning
    cannot take every batch (more overdue fixtures than one batch holds)."""
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    base = _first_upcoming(db_session, now)
    overdue = []
    for i in range(capacity + 1):
        f = Fixture(
            provider="mock",
            provider_id=f"overdue-{i}",
            league_id=base.league_id,
            season=base.season,
            round=base.round,
            home_team_id=base.home_team_id,
            away_team_id=base.away_team_id,
            kickoff_at=now - timedelta(hours=5 + i),  # overdue-0 is the most recent
            status="scheduled",
        )
        db_session.add(f)
        overdue.append(f)
    db_session.flush()
    asked: list[list[str]] = []

    def unresolved(ids):
        asked.append(list(ids))
        return []

    provider.get_fixtures_by_ids = unresolved
    first = reconcile_overdue_fixtures(db_session, provider, now=now, seen=set(), limit=capacity)
    second = reconcile_overdue_fixtures(db_session, provider, now=now, seen=set(), limit=capacity)
    assert first == (0, capacity) and second[0] == 0
    assert len(asked[0]) == capacity and asked[0][0] == "overdue-0"  # newest first
    assert overdue[-1].provider_id in asked[1]  # the one left out comes next
    assert {pid for batch in asked for pid in batch} == {f.provider_id for f in overdue}
    for f in overdue:
        db_session.refresh(f)
    assert all(f.reconcile_checked_at == now for f in overdue)


def _first_upcoming(session, now):
    return session.scalars(
        select(Fixture)
        .where(Fixture.status == "scheduled", Fixture.kickoff_at > now)
        .order_by(Fixture.kickoff_at, Fixture.id)
        .limit(1)
    ).one()


def test_ingestion_run_reconciles_and_reports(db_session):
    first = run_ingestion(db_session, _provider(FakeApiFootball()), now=REF)
    assert (first.fixtures_reconciled, first.overdue_unresolved) == (0, 0)
    # really played after the date window ends, stored with an old kickoff:
    # only the lookup by id can find it
    f = db_session.scalars(
        select(Fixture)
        .where(Fixture.status == "scheduled", Fixture.kickoff_at > REF + INGEST_LOOKAHEAD)
        .order_by(Fixture.kickoff_at)
    ).first()
    real_kickoff = f.kickoff_at
    f.kickoff_at = REF - timedelta(days=5)
    db_session.flush()
    again = run_ingestion(db_session, _provider(FakeApiFootball()), now=REF)
    assert (again.fixtures_reconciled, again.overdue_unresolved) == (1, 0)
    db_session.refresh(f)
    assert f.kickoff_at == real_kickoff


# --------------------------------------------- optional team news must not sink a run
def test_team_news_provider_error_keeps_the_rest_of_the_run(db_session):
    fake = FakeApiFootball()
    fake.overrides["/injuries"] = _error("injuries")
    res = run_pipeline(db_session, _provider(fake), now=REF, bookmaker="bet365", settings=NEWS)
    db_session.commit()
    assert "ProviderError" in res.team_news["error"]
    assert res.ingestion.odds_inserted > 0 and res.predictions.created > 0
    assert _count(db_session, TeamNewsSnapshot) == 0  # partial team news rolled back
    run = db_session.scalars(select(IngestionRun)).one()
    assert run.status == "success" and "error" in run.counts["team_news"]


def test_team_news_succeeds_when_the_provider_answers(db_session):
    res = run_pipeline(
        db_session, _provider(FakeApiFootball()), now=REF, bookmaker="bet365", settings=NEWS
    )
    db_session.commit()
    assert "error" not in res.team_news and res.team_news["absence_snapshots"] > 0


# ------------------------------------------------- core failures roll everything back
def test_failed_run_writes_nothing_and_is_logged(session_factory):
    fake = FakeApiFootball()
    fake.overrides["/odds"] = _error("odds")
    started = REF
    with session_factory() as s:
        with pytest.raises(ProviderError):
            run_pipeline(s, _provider(fake), now=REF, bookmaker="bet365", settings=NEWS)
        s.rollback()
        record_failed_run(
            "api_football", started, ProviderError("odds: request limit"), factory=session_factory
        )
    with session_factory() as s:
        for model in (League, Fixture, OddsSnapshot, Prediction, TeamNewsSnapshot):
            assert _count(s, model) == 0, model.__name__
        run = s.scalars(select(IngestionRun)).one()
        assert run.status == "failed" and "request limit" in run.error


# ----------------------------------------------------------- bad provider rows
class _BadOdds(MockProvider):
    def __init__(self, now, target: str):
        super().__init__(now)
        self.target = target

    def get_odds(self, kickoffs):
        def odds(fid, h, d, a):
            return OddsData(fid, "badbook", h, d, a, captured_at=self.reference_time)

        return [
            odds(self.target, 2.0, 3.4, 3.9),  # the only valid row
            odds(self.target, 1.0, 3.4, 3.9),  # 1.0 pays nothing back
            odds(self.target, 0.0, 3.4, 3.9),
            odds(self.target, float("inf"), 3.4, 3.9),
            odds(self.target, float("nan"), 3.4, 3.9),
            odds("no-such-fixture", 2.0, 3.4, 3.9),
        ]


def test_invalid_prices_and_unknown_fixtures_are_rejected(db_session, now):
    run_ingestion(db_session, MockProvider(now), now=now)
    target = db_session.scalars(
        select(Fixture.provider_id)
        .join(League, League.id == Fixture.league_id)
        .where(Fixture.status == "scheduled", Fixture.kickoff_at > now, League.has_odds)
        .order_by(Fixture.kickoff_at)
    ).first()
    inserted, rejected = ingest_odds(
        db_session, _BadOdds(now, target), now=now, lookahead=INGEST_LOOKAHEAD
    )
    assert (inserted, rejected) == (1, 5)
    assert _count(db_session, OddsSnapshot, OddsSnapshot.bookmaker == "badbook") == 1


def test_invalid_fixture_rows_are_skipped_and_duplicates_collapse(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    base = next(
        f for f in provider.get_fixtures(now, now + timedelta(days=3)) if f.status == "scheduled"
    )
    new = replace(base, provider_id="new-1")
    later = replace(new, kickoff_at=new.kickoff_at + timedelta(days=1))  # same id twice
    rows = [
        new,
        later,
        replace(base, provider_id="bad-status", status="abandoned"),
        replace(base, provider_id="bad-league", league_provider_id="nope"),
        replace(base, provider_id="bad-teams", away_team=base.home_team),
    ]
    _, changed = ingest_fixtures(db_session, provider.name, rows)
    assert changed == 1
    stored = db_session.scalars(
        select(Fixture).where(Fixture.provider_id.in_([r.provider_id for r in rows]))
    ).all()
    assert [(f.provider_id, f.kickoff_at) for f in stored] == [("new-1", later.kickoff_at)]


def test_rerun_does_not_rewrite_existing_fixtures(db_session, now):
    run_ingestion(db_session, MockProvider(now), now=now)
    again = run_ingestion(db_session, MockProvider(now), now=now)
    assert again.fixtures_changed == 0 and again.fixtures_reconciled == 0
