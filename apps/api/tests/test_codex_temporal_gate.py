"""Independent point-in-time guard regression using synthetic timestamps."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from edge_api.config import Settings
from edge_api.services.quality import assess
from edge_ml.model import FEATURE_SET, MODEL_VERSION


def test_quality_rejects_inputs_not_available_at_decision():
    decision = datetime(2026, 10, 16, tzinfo=UTC)
    future = decision + timedelta(hours=1)
    fixture = SimpleNamespace(status="scheduled", kickoff_at=decision + timedelta(hours=8))
    prediction = SimpleNamespace(
        id=1,
        created_at=future,
        input_data_as_of=future,
        model_version=SimpleNamespace(version=MODEL_VERSION, feature_set=FEATURE_SET),
        probability_home=0.6,
        probability_draw=0.2,
        probability_away=0.2,
        odds_snapshot=SimpleNamespace(captured_at=future),
        features={"matches_home": 30, "matches_away": 30},
    )
    report = assess(
        fixture,
        prediction,
        now=decision,
        settings=Settings(),
        last_run=SimpleNamespace(finished_at=future),
    )
    assert not report.ok, "Future prediction, odds and successful run all passed the quality gate"
