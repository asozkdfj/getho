"""Run with PR #11 packages on PYTHONPATH and a disposable QA database."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from edge_api.config import Settings
from edge_api.db.models import Prediction
from edge_api.services import queries


def test_review_excludes_predictions_created_after_kickoff(session_factory, seeded, now):
    from edge_api.services.review import review_day

    with session_factory() as session:
        fixtures = queries.fixtures_between(session, now, now + timedelta(days=4), "mock")
        predictions = queries.latest_predictions_by_fixture(session, [f.id for f in fixtures])
        fixture = next(f for f in fixtures if f.id in predictions)
        before = predictions[fixture.id]
        # Predictions are append-only. Move the synthetic fixture forward so
        # the existing server-timestamped prediction genuinely predates kickoff.
        fixture.kickoff_at = before.created_at + timedelta(days=1)
        fixture.status, fixture.home_score, fixture.away_score = "finished", 2, 0
        late = Prediction(
            fixture_id=fixture.id,
            model_version_id=before.model_version_id,
            market_odds_snapshot_id=before.market_odds_snapshot_id,
            input_data_as_of=fixture.kickoff_at - timedelta(minutes=1),
            created_at=fixture.kickoff_at + timedelta(hours=3),
            probability_home=0.98,
            probability_draw=0.01,
            probability_away=0.01,
            expected_goals_home=1.0,
            expected_goals_away=1.0,
            features=before.features,
        )
        session.add(late)
        session.flush()
        day = review_day(
            session,
            Settings(data_provider="mock"),
            fixture.kickoff_at.astimezone(ZoneInfo("Asia/Seoul")).date(),
            "Asia/Seoul",
        )
        item = next(i for i in day.items if i.fixture.id == fixture.id)
        assert item.prediction.id == before.id, {
            "selected": item.prediction.id,
            "expected": before.id,
            "created_at": str(item.prediction.created_at),
            "kickoff_at": str(fixture.kickoff_at),
        }
