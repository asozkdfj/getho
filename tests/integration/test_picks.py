"""Today's Pick: selection, quality gate, idempotent publication, settlement."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.config import Settings
from edge_api.db.models import DailyPick, DailyPickEvent, Fixture, IngestionRun
from edge_api.services import queries
from edge_api.services.evaluations import import_report
from edge_api.services.picks import (
    get_today_pick,
    local_day,
    pick_history,
    publish_daily_pick,
    settle_daily_picks,
)


def settings(**kw) -> Settings:
    base = {"data_provider": "mock", "ingest_max_age_hours": 10_000, "pick_min_probability": 0.0}
    return Settings(**(base | kw))


def _pick_time(session, now) -> tuple[datetime, Fixture]:
    """A moment on a KST day (after the 09:00 publish hour) with upcoming predicted
    fixtures: two hours before the earliest 12:30 UTC kickoff after ``now``."""
    fixtures = queries.fixtures_between(session, now, now + timedelta(days=4), "mock")
    preds = queries.latest_predictions_by_fixture(session, [f.id for f in fixtures])
    for f in fixtures:
        slot = (f.kickoff_at.hour, f.kickoff_at.minute) == (12, 30)
        if f.id in preds and slot and f.kickoff_at - timedelta(hours=2) > now:
            return f.kickoff_at - timedelta(hours=2), f
    raise AssertionError("mock schedule should have a 12:30 UTC fixture in the next days")


def test_local_day_uses_kst_boundaries():
    s = settings()
    late = local_day(datetime(2026, 10, 15, 14, 59, tzinfo=UTC), s)  # 23:59 KST
    nxt = local_day(datetime(2026, 10, 15, 15, 0, tzinfo=UTC), s)  # 00:00 KST next day
    assert late.day.isoformat() == "2026-10-15" and nxt.day.isoformat() == "2026-10-16"
    assert late.start_utc == datetime(2026, 10, 14, 15, tzinfo=UTC)
    assert late.end_utc == datetime(2026, 10, 15, 15, tzinfo=UTC)
    assert late.publish_at == datetime(2026, 10, 15, 0, tzinfo=UTC)  # 09:00 KST


def test_nothing_is_published_before_the_publish_hour(session_factory, seeded):
    with session_factory() as s:
        view = get_today_pick(s, settings(), datetime(2026, 10, 14, 23, 0, tzinfo=UTC))  # 08:00 KST
        assert view.status == "scheduled" and view.pick is None
        assert s.scalar(select(func.count()).select_from(DailyPick)) == 0


def test_publishes_highest_probability_eligible_outcome(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        s.commit()
        assert pick.status == "published"
        ev = pick.evidence
        eligible = [c for c in ev["candidates"] if c["eligible"]]
        assert eligible and pick.probability == max(c["best_probability"] for c in eligible)
        assert ev["chosen"]["outcome"] == pick.outcome
        assert pick.fixture.kickoff_at > pick_now
        assert pick.prediction.fixture_id == pick.fixture_id
        assert pick.input_data_as_of == pick.prediction.input_data_as_of
        assert ev["is_demo"] is True and ev["factors_used"]
        assert all(c["passed"] for c in ev["chosen"]["quality_checks"])
        probs = ev["chosen"]["probabilities"]
        assert sum(probs.values()) == pytest.approx(1.0)


def test_publication_is_idempotent(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        first = publish_daily_pick(s, settings(), pick_now)
        s.commit()
    with session_factory() as s2:  # another worker / request / restart
        again = publish_daily_pick(s2, settings(pick_min_probability=0.99), pick_now)
        view = get_today_pick(s2, settings(), pick_now + timedelta(minutes=5))
        s2.commit()
        assert again.id == first.id and view.pick.id == first.id
        assert s2.scalar(select(func.count()).select_from(DailyPick)) == 1


def test_no_qualifying_match_when_threshold_is_unreachable(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(pick_min_probability=0.99), pick_now)
        assert pick.status == "no_qualifying_match" and pick.fixture_id is None
        assert any(
            "below_min_probability" in c["excluded_reasons"] for c in pick.evidence["candidates"]
        )


def test_no_matches_day(session_factory, seeded, now):
    with session_factory() as s:
        pick = publish_daily_pick(s, settings(), now + timedelta(days=400))
        assert pick.status == "no_matches" and pick.evidence["matches_today"] == 0


def test_started_and_low_quality_matches_are_excluded(session_factory, seeded, now):
    with session_factory() as s:
        _, f = _pick_time(s, now)
        after_kickoff = f.kickoff_at + timedelta(minutes=1)
        pick = publish_daily_pick(s, settings(), after_kickoff)
        started = next(c for c in pick.evidence["candidates"] if c["fixture_id"] == f.id)
        assert "upcoming" in started["excluded_reasons"] and pick.fixture_id != f.id


def test_stale_data_blocks_the_pick(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        s.execute(text("TRUNCATE ingestion_runs"))
        s.add(
            IngestionRun(
                provider="mock",
                started_at=now - timedelta(days=3),
                finished_at=now - timedelta(days=3),
                status="success",
            )
        )
        s.flush()
        pick = publish_daily_pick(s, settings(ingest_max_age_hours=6), pick_now)
        assert pick.status == "no_qualifying_match"
        assert all("ingestion_recent" in c["excluded_reasons"] for c in pick.evidence["candidates"])


def test_insufficient_team_history_blocks_the_pick(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(min_team_matches=10_000), pick_now)
        assert pick.status == "no_qualifying_match"


def test_settlement_and_voiding_are_appended_once(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        f = pick.fixture
        f.status, f.home_score, f.away_score = "finished", 2, 1
        s.flush()
        assert settle_daily_picks(s, settings(), pick_now + timedelta(days=1))["settled"] == 1
        assert settle_daily_picks(s, settings(), pick_now + timedelta(days=1))["settled"] == 0
        event = s.scalars(select(DailyPickEvent)).one()
        assert event.actual_outcome == "HOME" and event.hit == (pick.outcome == "HOME")

        other = publish_daily_pick(s, settings(), pick_now + timedelta(days=1))
        if other.status == "published":
            other.fixture.status = "postponed"
            s.flush()
            counts = settle_daily_picks(s, settings(), pick_now + timedelta(days=1))
            assert counts["voided"] == 1 and counts["republished"] == 0
        summary = pick_history(s, settings(), 10)["summary"]
        assert summary["settled"] == 1 and summary["hits"] == int(event.hit)
        assert summary["mean_probability"] == pytest.approx(pick.probability)


def test_replace_on_void_publishes_a_new_revision(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        s_replace = settings(pick_replace_on_void=True)
        pick = publish_daily_pick(s, s_replace, pick_now)
        pick.fixture.status = "cancelled"
        s.flush()
        assert settle_daily_picks(s, s_replace, pick_now)["republished"] == 1
        revisions = s.scalars(select(DailyPick.revision).order_by(DailyPick.revision)).all()
        assert revisions == [1, 2]
        second = s.scalars(select(DailyPick).where(DailyPick.revision == 2)).one()
        assert second.fixture_id != pick.fixture_id


def test_daily_picks_are_append_only(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        publish_daily_pick(s, settings(), pick_now)
        s.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE daily_picks SET probability = 0.99"))


def test_pipeline_publishes_and_logs_runs(session_factory, seeded, now):
    from edge_ingestion.jobs import run_pipeline
    from edge_ingestion.providers import MockProvider

    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        res = run_pipeline(
            s, MockProvider(now), now=pick_now, bookmaker="mockbook", settings=settings()
        )
        s.commit()
        assert res.picks["published"] in ("published", "no_qualifying_match", "no_matches")
        assert s.scalar(select(func.count()).select_from(IngestionRun)) >= 2


def test_report_import_is_deduplicated(session_factory):
    with session_factory() as s:
        first = import_report(s)
        second = import_report(s)
        assert first is not None and second is None


def test_published_pick_cites_the_backtest_of_the_current_model(session_factory, seeded, now):
    with session_factory() as s:
        import_report(s)
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(pick_min_probability=0.55), pick_now)
        bt = pick.evidence["backtest"]
        assert bt is not None and bt["threshold"] <= 0.55 and bt["days_with_pick"] > 0


def test_pick_scope_limits_candidate_leagues(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(pick_leagues="esp-1"), pick_now)
        ev = pick.evidence
        assert ev["eligible_leagues"] == ["esp-1"] and ev["league_scope"] == "esp-1"
        assert ev["matches_today"] >= ev["matches_in_scope"]
        assert {c["league"] for c in ev["candidates"]} <= {"La Liga"}
        if pick.fixture is not None:
            assert pick.fixture.league.provider_id == "esp-1"


def test_verified_scope_on_mock_is_demo_wide(session_factory, seeded, now):
    from edge_api.services.picks import eligible_league_ids

    with session_factory() as s:
        assert eligible_league_ids(s, settings(pick_leagues="verified")) is None
        assert eligible_league_ids(s, settings(pick_leagues="all")) is None


def test_verified_leagues_come_from_the_backtest_report(session_factory):
    from edge_api.services.leagues import verified_league_ids
    from edge_api.services.picks import eligible_league_ids

    with session_factory() as s:
        assert verified_league_ids(s, "api_football") == frozenset()  # no report yet
        import_report(s)
        verified = verified_league_ids(s, "api_football")
        assert {"39", "140", "78"} <= verified  # league ids of the backtested leagues
        assert verified_league_ids(s, "mock") == frozenset()  # synthetic data is never verified
        real = settings(data_provider="api_football", pick_leagues="verified")
        assert eligible_league_ids(s, real) == verified
