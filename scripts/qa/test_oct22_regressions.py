from datetime import timedelta

from sqlalchemy import select
from tests.integration.test_personal_picks import _body, _upcoming_with_prediction

from conftest import set_test_wall_clock
from edge_api.db.models import Fixture, TeamNewsKind, TeamNewsSnapshot
from edge_ingestion.availability_readiness import _first_captured, _lead_hours


def test_finished_fixture_cannot_be_prospective(client, session_factory, now):
    with session_factory() as session:
        fixture, _ = _upcoming_with_prediction(session, now)
        fixture.status = "finished"
        fixture.home_score, fixture.away_score = 1, 0
        session.commit()
    response = client.post("/personal-picks", json=_body(fixture.id, key="finished-key"))
    assert response.status_code == 422 or (
        response.status_code == 200
        and response.json()["current"]["source_type"] != "prospective_record"
    ), response.text


def test_lead_time_uses_actual_storage_availability(session_factory, seeded, now):
    with session_factory() as session:
        fixture = session.scalars(
            select(Fixture).where(Fixture.status == "finished").order_by(Fixture.kickoff_at.desc())
        ).first()
        set_test_wall_clock(session, fixture.kickoff_at - timedelta(hours=1))
        for team in (fixture.home_team_id, fixture.away_team_id):
            session.add(
                TeamNewsSnapshot(
                    fixture_id=fixture.id,
                    team_id=team,
                    provider="mock",
                    kind="absences",
                    payload={"players": []},
                    content_hash=f"late-{fixture.id}-{team}",
                    captured_at=fixture.kickoff_at - timedelta(hours=30),
                )
            )
        session.flush()
        first = _first_captured(session, TeamNewsKind.ABSENCES)
        assert _lead_hours([fixture], first) == [1.0]
