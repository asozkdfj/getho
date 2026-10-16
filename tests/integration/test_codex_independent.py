"""Independent QA expectations; failures are reported, not production patches."""

from datetime import timedelta

from edge_api.api.deps import get_now
from edge_api.db.models import OddsSnapshot
from edge_api.services.prediction_job import run_prediction_job
from tests.integration.test_api import _upcoming_with_prediction


def test_selection_price_is_not_silently_replaced(client, session_factory, now):
    fixtures = _upcoming_with_prediction(client, 2)
    shown = fixtures[0]["prediction_odds"]["odds_home"]
    with session_factory() as session:
        old = fixtures[0]["prediction_odds"]
        session.add(
            OddsSnapshot(
                fixture_id=fixtures[0]["id"],
                provider="mock",
                bookmaker="mockbook",
                market="1X2",
                captured_at=now + timedelta(seconds=1),
                odds_home=9.0,
                odds_draw=old["odds_draw"],
                odds_away=old["odds_away"],
                raw_payload={},
            )
        )
        session.flush()
        run_prediction_job(
            session, now=now + timedelta(seconds=2), bookmaker="mockbook", provider="mock"
        )
        session.commit()
    client.app.dependency_overrides[get_now] = lambda: now + timedelta(seconds=3)
    response = client.post(
        "/combinations/analyze",
        json={"selections": [{"fixture_id": f["id"], "outcome": "HOME"} for f in fixtures]},
    )
    assert response.status_code == 409 or (
        response.status_code == 200 and response.json()["legs"][0]["decimal_odds"] == shown
    ), f"Displayed {shown}, silently returned {response.json()['legs'][0]['decimal_odds']}"
