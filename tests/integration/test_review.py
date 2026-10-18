"""Match review: pre-kickoff predictions next to results."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from edge_api.config import Settings
from edge_api.db.models import Fixture, Prediction
from edge_api.services import queries
from edge_api.services.review import review_day

KST = "Asia/Seoul"


def settings(**kw) -> Settings:
    base = {"data_provider": "mock", "ingest_max_age_hours": 10_000, "pick_min_probability": 0.0}
    return Settings(**(base | kw))


def _finished_fixture(session, now) -> tuple[Fixture, Prediction]:
    """An upcoming predicted fixture, then played: home win 2-0."""
    fixtures = queries.fixtures_between(session, now, now + timedelta(days=4), "mock")
    preds = queries.latest_predictions_by_fixture(session, [f.id for f in fixtures])
    f = next(f for f in fixtures if f.id in preds)
    f.status, f.home_score, f.away_score = "finished", 2, 0
    session.flush()
    return f, preds[f.id]


def _local_day(f: Fixture):
    return f.kickoff_at.astimezone(ZoneInfo(KST)).date()


def test_review_shows_the_pre_kickoff_prediction_and_the_result(session_factory, seeded, now):
    with session_factory() as s:
        f, before = _finished_fixture(s, now)
        # a prediction built from data after kickoff must never be shown as "what we said"
        s.add(
            Prediction(
                fixture_id=f.id,
                model_version_id=before.model_version_id,
                market_odds_snapshot_id=before.market_odds_snapshot_id,
                input_data_as_of=f.kickoff_at + timedelta(hours=1),
                probability_home=0.01,
                probability_draw=0.01,
                probability_away=0.98,
                expected_goals_home=1.0,
                expected_goals_away=1.0,
                features=before.features,
            )
        )
        s.flush()
        day = review_day(s, settings(), _local_day(f), KST)
        item = next(i for i in day.items if i.fixture.id == f.id)
        assert item.prediction.id == before.id
        assert item.actual.value == "HOME"
        assert item.hit == (item.top[0].value == "HOME")
        assert item.market is not None and item.market_hit is not None
        done = [i for i in day.items if i.evaluated]
        summary = day.summaries["verified"]  # demo data: every league is in scope
        assert summary["matches"] == len(done) >= 1
        assert summary["hits"] == sum(1 for i in done if i.hit)
        assert summary["expected_hits"] == pytest.approx(sum(i.top[1] for i in done))
        tiers = summary["tiers"]
        assert tiers["high"]["matches"] + tiers["medium"]["matches"] <= summary["matches"]


def test_unplayed_and_unpredicted_matches_are_listed_but_not_scored(session_factory, seeded, now):
    with session_factory() as s:
        f, _ = _finished_fixture(s, now)
        day = review_day(s, settings(), _local_day(f), KST)
        others = [i for i in day.items if i.fixture.id != f.id]
        assert all(i.hit is None for i in others if i.actual is None)
        assert all(not i.evaluated for i in day.items if i.prediction is None)


def test_review_endpoint(client, session_factory, now):
    with session_factory() as s:
        f, _ = _finished_fixture(s, now)
        s.commit()
        date = _local_day(f).isoformat()
    body = client.get(f"/review?date={date}").json()
    assert body["date"] == date and body["tz"] == KST and body["is_demo"] is True
    item = next(i for i in body["items"] if i["fixture_id"] == f.id)
    assert item["actual_outcome"] == "HOME" and item["hit"] in (True, False)
    assert item["model_probabilities"] and item["market_probabilities"]
    assert body["summary"]["matches"] >= 1 and "note" in body
    # default: the day before "now" in the pick timezone
    default = client.get("/review").json()
    assert default["date"] == (now.astimezone(ZoneInfo(KST)).date() - timedelta(days=1)).isoformat()
    assert client.get("/review?tz=Mars/Base").status_code == 422


def test_review_includes_that_days_pick(session_factory, seeded, now):
    from edge_api.services.picks import publish_daily_pick

    with session_factory() as s:
        fixtures = queries.fixtures_between(s, now, now + timedelta(days=4), "mock")
        pick_time = fixtures[0].kickoff_at - timedelta(hours=2)
        pick = publish_daily_pick(s, settings(), pick_time)
        day = review_day(s, settings(), pick.pick_date, KST)
        assert day.pick is not None and day.pick.id == pick.id
        assert s.scalars(select(Fixture)).first() is not None


def test_cli_review_text(session_factory, seeded, now, monkeypatch):
    from contextlib import contextmanager

    import edge_ingestion.cli as cli

    with session_factory() as s:
        f, _ = _finished_fixture(s, now)
        s.commit()

    @contextmanager
    def scope():
        with session_factory() as s:
            yield s

    monkeypatch.setattr(cli, "session_scope", scope)
    text = cli.review_text(settings(), _local_day(f).isoformat(), KST)
    assert "경기 복기" in text and "기대" in text
    assert f"{f.home_team.name} 2:0 {f.away_team.name}" in text


def test_cli_review_runs_as_a_module(session_factory, seeded, now):
    """`python -m edge_ingestion.cli review` (catches definitions below the main guard)."""
    import os
    import subprocess
    import sys

    from conftest import TEST_DATABASE_URL

    with session_factory() as s:
        f, _ = _finished_fixture(s, now)
        s.commit()
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL, "DATA_PROVIDER": "mock"}
    out = subprocess.run(
        [sys.executable, "-m", "edge_ingestion.cli", "review", "--date", str(_local_day(f))],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert "경기 복기" in out.stdout and f.home_team.name in out.stdout
