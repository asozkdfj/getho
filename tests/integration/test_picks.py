"""Today's Pick: selection, quality gate, idempotent publication, settlement."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.config import Settings
from edge_api.db.models import DailyPick, DailyPickEvent, Fixture, IngestionRun, Prediction
from edge_api.services import queries
from edge_api.services.evaluations import import_report
from edge_api.services.picks import (
    POLICY_VERSION,
    get_today_pick,
    local_day,
    pick_history,
    publish_daily_pick,
    settle_daily_picks,
)
from edge_ingestion.jobs import run_pipeline
from edge_ingestion.providers import MockProvider


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


def test_pick_day_runs_from_the_publish_hour_to_the_next_morning():
    s = settings()
    publish = datetime(2026, 10, 15, 0, tzinfo=UTC)  # 09:00 KST on the 15th
    for moment in (
        publish,  # 09:00 KST
        datetime(2026, 10, 15, 14, 59, tzinfo=UTC),  # 23:59 KST
        datetime(2026, 10, 15, 17, 0, tzinfo=UTC),  # 02:00 KST on the 16th (European evening)
        datetime(2026, 10, 15, 23, 59, tzinfo=UTC),  # 08:59 KST on the 16th
    ):
        ld = local_day(moment, s)
        assert ld.day.isoformat() == "2026-10-15"
        assert ld.start_utc == ld.publish_at == publish
        assert ld.end_utc == datetime(2026, 10, 16, 0, tzinfo=UTC)  # 09:00 KST on the 16th
    assert local_day(datetime(2026, 10, 16, 0, tzinfo=UTC), s).day.isoformat() == "2026-10-16"


def test_before_the_publish_hour_the_previous_pick_is_current(session_factory, seeded):
    with session_factory() as s:
        moment = datetime(2026, 10, 14, 23, 0, tzinfo=UTC)  # 08:00 KST on the 15th
        view = get_today_pick(s, settings(), moment, publish_if_due=False)
        assert view.day.day.isoformat() == "2026-10-14"  # published at 09:00 the day before
        assert view.day.end_utc == datetime(2026, 10, 15, 0, tzinfo=UTC)
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
        ld = local_day(pick_now, settings())
        assert ld.start_utc <= pick.fixture.kickoff_at < ld.end_utc
        assert ev["window_utc"] == [ld.start_utc.isoformat(), ld.end_utc.isoformat()]
        assert pick.policy["window"] == "publish_hour_to_next_day_publish_hour"
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


def _future_prediction(session, fixture: Fixture, available_at: datetime) -> Prediction:
    """A copy of the fixture's latest prediction whose inputs only exist from
    ``available_at`` on, made overwhelmingly confident so the rule would pick it."""
    base = queries.latest_prediction(session, fixture.id)
    p = Prediction(
        fixture_id=fixture.id,
        model_version_id=base.model_version_id,
        market_odds_snapshot_id=base.market_odds_snapshot_id,
        input_data_as_of=available_at,
        probability_home=0.97,
        probability_draw=0.02,
        probability_away=0.01,
        expected_goals_home=base.expected_goals_home,
        expected_goals_away=base.expected_goals_away,
        features=base.features,
    )
    session.add(p)
    session.flush()
    return p


def test_decision_only_sees_predictions_known_at_decision_time(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, f = _pick_time(s, now)
        future = _future_prediction(s, f, available_at=pick_now + timedelta(hours=1))
        pick = publish_daily_pick(s, settings(), pick_now)
        assert pick.prediction_id != future.id
        assert all(c.get("best_probability") != 0.97 for c in pick.evidence["candidates"])
        # once its inputs exist, the same rule does use it (and picks it)
        later = publish_daily_pick(s, settings(), pick_now + timedelta(minutes=90), revision=2)
        assert later.prediction_id == future.id and later.probability == pytest.approx(0.97)


def test_decision_time_and_policy_version_are_recorded(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        assert pick.policy["version"] == POLICY_VERSION == 2
        assert pick.policy["window"] == "publish_hour_to_next_day_publish_hour"
        assert pick.evidence["decided_at"] == pick_now.isoformat()
        assert pick.evidence["last_collection_at"] is not None
        assert pick.input_data_as_of <= pick_now


def test_live_record_counts_only_picks_written_before_kickoff(session_factory, seeded, now):
    real = settings(data_provider="api_football")
    with session_factory() as s:
        fixtures = s.scalars(
            select(Fixture).where(Fixture.status == "scheduled").order_by(Fixture.id).limit(2)
        ).all()
        preds = queries.latest_predictions_by_fixture(s, [f.id for f in fixtures])
        for i, (f, written) in enumerate(
            [(fixtures[0], -timedelta(hours=3)), (fixtures[1], timedelta(hours=1))]
        ):
            f.status, f.home_score, f.away_score = "finished", 1, 0
            s.add(
                DailyPick(
                    provider="api_football",
                    pick_date=now.date() + timedelta(days=i),
                    tz="Asia/Seoul",
                    status="published",
                    fixture_id=f.id,
                    prediction_id=preds[f.id].id,
                    outcome="HOME",
                    probability=0.6,
                    evidence={},
                    policy={},
                    published_at=f.kickoff_at + written,  # second one: after kickoff
                )
            )
        s.flush()
        assert settle_daily_picks(s, real, now + timedelta(days=5))["settled"] == 2
        summary = pick_history(s, real, 10)["summary"]
        assert (summary["published"], summary["settled"], summary["hits"]) == (1, 1, 1)
        assert summary["late_recorded"] == 1
        flags = sorted(
            (p.published_at < p.fixture.kickoff_at) for p in pick_history(s, real, 10)["picks"]
        )
        assert flags == [False, True]  # both stay listed, only one counts


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


def test_pick_on_a_rescheduled_match_is_voided(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        f = pick.fixture
        f.kickoff_at += timedelta(minutes=30)  # moved within the pick day: still counts
        s.flush()
        assert settle_daily_picks(s, settings(), pick_now)["voided"] == 0
        f.kickoff_at += timedelta(days=3)  # provider moved it to another day
        s.flush()
        assert settle_daily_picks(s, settings(), pick_now)["voided"] == 1
        event = s.scalars(select(DailyPickEvent)).one()
        assert event.event == "voided" and event.reason == "fixture rescheduled"
        assert settle_daily_picks(s, settings(), pick_now)["voided"] == 0  # appended once
        # the original pick row is kept as published
        assert s.scalars(select(DailyPick)).one().fixture_id == f.id


@pytest.mark.parametrize("first_seen", ["scheduled", "live", "finished"])
def test_moved_pick_is_voided_whatever_state_the_match_is_first_seen_in(
    session_factory, seeded, now, first_seen
):
    """Codex QA F3: a match moved off the pick day is voided before settlement, even
    when the next collection already sees it live or finished."""
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        f = pick.fixture
        f.kickoff_at += timedelta(days=3)
        f.status = first_seen
        if first_seen == "finished":
            f.home_score, f.away_score = 2, 1
        s.flush()
        later = f.kickoff_at + timedelta(hours=3)
        assert settle_daily_picks(s, settings(), later) == {
            "settled": 0,
            "voided": 1,
            "republished": 0,
        }
        assert settle_daily_picks(s, settings(), later)["voided"] == 0  # appended once
        event = s.scalars(select(DailyPickEvent)).one()
        assert event.event == "voided" and event.reason == "fixture rescheduled"


def test_match_finished_inside_the_pick_day_is_settled(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        f = pick.fixture
        f.kickoff_at += timedelta(minutes=30)  # still inside the window
        f.status, f.home_score, f.away_score = "finished", 1, 1
        s.flush()
        result = settle_daily_picks(s, settings(), f.kickoff_at + timedelta(hours=3))
        assert (result["settled"], result["voided"]) == (1, 0)


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
        # the replay with the service's timing is cited, not the whole-day count
        assert bt["decision_hour"] == 9


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


# ------------------------------------------------- decision time (Codex QA F2)
def test_live_pipeline_decides_after_its_own_writes(session_factory, now, monkeypatch):
    """Production: the run's rows are stamped just after the ``now`` it started
    with, and the pick must still be published from them."""
    from conftest import set_test_wall_clock
    from edge_ingestion import jobs

    monkeypatch.setattr(jobs, "utcnow", lambda: now + timedelta(seconds=40))
    with session_factory() as s:
        set_test_wall_clock(s, now + timedelta(seconds=5))  # DB clock: transaction start
        result = run_pipeline(
            s, MockProvider(now), now=now, bookmaker="mockbook", settings=settings()
        )
        assert result.picks["published"] == "published"
        pick = s.scalars(select(DailyPick)).one()
        assert pick.evidence["decided_at"] == (now + timedelta(seconds=40)).isoformat()


def test_pipeline_pinned_to_an_earlier_time_publishes_nothing_from_later_rows(
    session_factory, now, monkeypatch
):
    """A replay at a past ``now`` whose rows are recorded later cannot claim a pick."""
    from conftest import set_test_wall_clock
    from edge_ingestion import jobs

    monkeypatch.setattr(jobs, "utcnow", lambda: now + timedelta(hours=1))
    with session_factory() as s:
        set_test_wall_clock(s, now + timedelta(hours=1))
        result = run_pipeline(
            s,
            MockProvider(now),
            now=now,
            bookmaker="mockbook",
            settings=settings(),
            decision_at=now,
        )
        assert result.picks["published"] == "no_qualifying_match"
        candidates = s.scalars(select(DailyPick)).one().evidence["candidates"]
        predicted = [row for row in candidates if "best_outcome" in row]
        assert predicted
        for row in predicted:
            assert {"prediction_timely", "ingestion_recent"} <= set(row["excluded_reasons"])
