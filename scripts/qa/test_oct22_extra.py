from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from tests.integration.test_alerts import SETTINGS, Outbox
from tests.integration.test_personal_picks import _body, _upcoming_with_prediction

from conftest import set_test_wall_clock
from edge_api.db.models import DailyPick, FixtureObservation
from edge_api.services.alerts import check


def test_new_pick_day_does_not_claim_missing_pick_was_recorded(session_factory, seeded):
    out = Outbox()
    before = datetime(2026, 10, 22, 23, 50, tzinfo=UTC)  # 08:50 KST next day
    after = before + timedelta(minutes=20)  # new pick day, within grace period
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(DailyPick)) == 0
        set_test_wall_clock(session, before)
        first = {r["key"]: r for r in check(session, SETTINGS, before, out)}
        assert first["pick_missing"]["action"] == "firing"
        set_test_wall_clock(session, after)
        second = {r["key"]: r for r in check(session, SETTINGS, after, out)}
        assert session.scalar(select(func.count()).select_from(DailyPick)) == 0
        message = second["pick_missing"].get("message", "")
        assert "결정이 기록됐어요" not in message, message


def test_away_only_score_observation_cannot_be_prospective(client, session_factory, now):
    with session_factory() as session:
        fixture, _ = _upcoming_with_prediction(session, now)
        session.add(
            FixtureObservation(
                fixture_id=fixture.id,
                provider="mock",
                status="scheduled",
                kickoff_at=fixture.kickoff_at,
                home_score=None,
                away_score=1,
                created_at=now - timedelta(minutes=1),
            )
        )
        session.commit()
    response = client.post("/personal-picks", json=_body(fixture.id, key="away-score-only"))
    source = response.json().get("current", {}).get("source_type")
    assert response.status_code == 422 or (
        response.status_code == 200 and source != "prospective_record"
    ), f"HTTP {response.status_code}; source={source}"
