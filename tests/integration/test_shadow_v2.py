"""Shadow-v2: the shot-based form candidate recorded at the pick decision from
decision-time inputs only (docs/experiments/shadow-v2-2026.md)."""

from datetime import timedelta

import numpy as np
import pytest
from sqlalchemy import select

from edge_api.config import Settings
from edge_api.db.models import (
    Fixture,
    FixtureObservation,
    MatchStatistic,
    Prediction,
    ShadowForecast,
)
from edge_api.services.picks import publish_daily_pick
from edge_api.services.shadow_v2 import shadow_v2_report, shot_histories
from edge_ingestion.providers import MockProvider
from edge_ingestion.team_news import ingest_team_news
from edge_ml.shadow_v2 import PROTOCOL, shot_adjusted
from tests.integration.test_picks import _pick_time, settings


@pytest.fixture
def with_statistics(session_factory, seeded, now):
    """Post-match statistics of every finished mock fixture, stored by ``now``."""
    with session_factory() as s:
        ingest_team_news(
            s,
            MockProvider(now),
            now=now,
            settings=Settings(team_news_leagues="all", appearances_per_run=10_000),
        )
        s.commit()


def _rows(s):
    return s.scalars(
        select(ShadowForecast)
        .where(ShadowForecast.protocol == PROTOCOL)
        .order_by(ShadowForecast.fixture_id)
    ).all()


def test_every_window_fixture_gets_a_v2_row_next_to_v1(session_factory, with_statistics, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        v1 = s.scalars(select(ShadowForecast).where(ShadowForecast.protocol == "shadow-v1")).all()
        v2 = _rows(s)
        assert {r.fixture_id for r in v2} == {r.fixture_id for r in v1}
        assert pick.evidence["shadow_v2"]["protocol"] == PROTOCOL
        assert "error" not in pick.evidence["shadow_v2"]
        reasons = {r.excluded_reason for r in v2 if r.status == "excluded"}
        assert reasons <= {
            "not_upcoming",
            "no_prediction",
            "prediction_after_decision",
            "no_market_odds",
            "stale_market_odds",
            "invalid_market_odds",
            "insufficient_shot_history",
        }
        recorded = [r for r in v2 if r.status == "recorded"]
        assert recorded, "mock teams have enough matches with statistics"
        for r in recorded:
            f = r.forecasts
            assert set(f) >= {"production", "market", "production_shots_v1", "inputs"}
            assert min(f["inputs"]["matches_home"], f["inputs"]["matches_away"]) >= 5
            assert abs(sum(f["production_shots_v1"]) - 1) < 1e-9
            # with neutral features the candidate is exactly the production forecast
            p = s.get(Prediction, r.prediction_id)
            neutral = shot_adjusted(p.expected_goals_home, p.expected_goals_away, [0] * 4, [0] * 4)
            assert neutral == pytest.approx(f["production"], abs=1e-9)
        # same day again: nothing new
        publish_daily_pick(s, settings(), pick_now + timedelta(minutes=5))
        assert len(_rows(s)) == len(v2)


def test_statistics_stored_after_the_decision_are_not_used(session_factory, with_statistics, now):
    from conftest import set_test_wall_clock

    with session_factory() as s:
        pick_now, fixture = _pick_time(s, now)
        league = {fixture.league_id}
        before = shot_histories(s, "mock", league, pick_now)[fixture.league_id]
        team = str(fixture.home_team_id)
        counted = before.count(team, pick_now)
        x_before = before.features(team, pick_now, "sot_and_finishing")
        # a revised statistics row for one of the team's matches, stored later
        old = s.scalars(
            select(MatchStatistic).where(MatchStatistic.team_id == fixture.home_team_id)
        ).first()
        assert old is not None
        set_test_wall_clock(s, pick_now + timedelta(hours=1))
        s.add(
            MatchStatistic(
                fixture_id=old.fixture_id,
                team_id=old.team_id,
                provider="mock",
                shots=(old.shots or 0) + 20,
                shots_on_target=(old.shots_on_target or 0) + 15,
                expected_goals=old.expected_goals,
                source="ingest",
            )
        )
        s.flush()
        again = shot_histories(s, "mock", league, pick_now)[fixture.league_id]
        assert again.count(team, pick_now) == counted
        assert np.allclose(again.features(team, pick_now, "sot_and_finishing"), x_before)
        later = shot_histories(s, "mock", league, pick_now + timedelta(hours=2))[fixture.league_id]
        assert not np.allclose(later.features(team, pick_now, "sot_and_finishing"), x_before)


def _observe(s, f, at, **state):
    """Store a new state of ``f`` at ``at`` in the fixture row and its history."""
    from conftest import set_test_wall_clock

    for k, v in state.items():
        setattr(f, k, v)
    set_test_wall_clock(s, at)
    s.add(
        FixtureObservation(
            fixture_id=f.id,
            provider="mock",
            status=f.status,
            kickoff_at=f.kickoff_at,
            home_score=f.home_score,
            away_score=f.away_score,
        )
    )
    s.flush()


def _counted_match(s, fixture, pick_now):
    """A finished match of the fixture's home team that its shot history counts."""
    return s.scalars(
        select(Fixture)
        .join(MatchStatistic, MatchStatistic.fixture_id == Fixture.id)
        .where(
            Fixture.league_id == fixture.league_id,
            Fixture.home_team_id == fixture.home_team_id,
            Fixture.status == "finished",
            Fixture.kickoff_at < pick_now - timedelta(days=1),
        )
        .order_by(Fixture.kickoff_at.desc())
    ).first()


def test_a_later_score_correction_does_not_change_an_earlier_decision(
    session_factory, with_statistics, now
):
    """Scores as observed by the decision, not the current row (Codex SHOT-1)."""
    with session_factory() as s:
        pick_now, fixture = _pick_time(s, now)
        league, team = {fixture.league_id}, str(fixture.home_team_id)
        x_before = shot_histories(s, "mock", league, pick_now)[fixture.league_id].features(
            team, pick_now, "sot_and_finishing"
        )
        match = _counted_match(s, fixture, pick_now)
        _observe(
            s,
            match,
            pick_now + timedelta(hours=1),
            home_score=match.home_score + 3,
            away_score=match.away_score,
        )
        again = shot_histories(s, "mock", league, pick_now)[fixture.league_id]
        assert np.allclose(again.features(team, pick_now, "sot_and_finishing"), x_before)
        later = shot_histories(s, "mock", league, pick_now + timedelta(hours=2))
        x_later = later[fixture.league_id].features(team, pick_now, "sot_and_finishing")
        assert not np.allclose(x_later, x_before)


def test_a_result_not_yet_observed_at_the_decision_is_left_out(
    session_factory, with_statistics, now
):
    """Finished in the current row, but the decision saw it as not finished."""
    with session_factory() as s:
        pick_now, fixture = _pick_time(s, now)
        league, team = {fixture.league_id}, str(fixture.home_team_id)
        x_before = shot_histories(s, "mock", league, pick_now)[fixture.league_id].features(
            team, pick_now, "sot_and_finishing"
        )
        match = _counted_match(s, fixture, pick_now)
        final = {"status": match.status, "home_score": match.home_score}
        # reopened before the decision, final again only after it
        _observe(s, match, pick_now - timedelta(hours=1), status="live")
        _observe(s, match, pick_now + timedelta(hours=1), **final)
        at_decision = shot_histories(s, "mock", league, pick_now)[fixture.league_id]
        # the window of the last 10 matches reaches one match further back
        assert not np.allclose(at_decision.features(team, pick_now, "sot_and_finishing"), x_before)
        after = shot_histories(s, "mock", league, pick_now + timedelta(hours=2))
        x_after = after[fixture.league_id].features(team, pick_now, "sot_and_finishing")
        assert np.allclose(x_after, x_before)


def test_the_kickoff_known_at_the_decision_is_used(session_factory, with_statistics, now):
    """A match moved after the decision keeps the kickoff the decision knew."""
    with session_factory() as s:
        pick_now, fixture = _pick_time(s, now)
        league, team = {fixture.league_id}, str(fixture.home_team_id)
        x_before = shot_histories(s, "mock", league, pick_now)[fixture.league_id].features(
            team, pick_now, "sot_and_finishing"
        )
        match = _counted_match(s, fixture, pick_now)
        # recorded later as having kicked off after the decision
        _observe(s, match, pick_now + timedelta(hours=1), kickoff_at=pick_now + timedelta(days=1))
        again = shot_histories(s, "mock", league, pick_now)[fixture.league_id]
        assert np.allclose(again.features(team, pick_now, "sot_and_finishing"), x_before)


def test_report_is_provisional_and_withholds_the_decision(session_factory, with_statistics, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        report = shadow_v2_report(s, "mock", now=pick_now, start=pick.pick_date, end=pick.pick_date)
        assert report["protocol"] == PROTOCOL and report["status"] == "provisional"
        assert report["decision"] == {}
        assert report["recorded"] + sum(report["excluded"].values()) == report["rows"]


def test_a_failing_v2_record_never_blocks_the_pick_or_v1(
    session_factory, with_statistics, now, monkeypatch
):
    from edge_api.services import picks as picks_module

    def broken(*args, **kwargs):
        raise RuntimeError("shot history unavailable")

    monkeypatch.setattr(picks_module, "record_shadow_v2", broken)
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        assert pick.id is not None
        assert pick.evidence["shadow_v2"]["error"].startswith("RuntimeError")
        assert "error" not in pick.evidence["shadow"]
        assert _rows(s) == []
        v1 = s.scalars(select(ShadowForecast).where(ShadowForecast.protocol == "shadow-v1")).all()
        assert v1
