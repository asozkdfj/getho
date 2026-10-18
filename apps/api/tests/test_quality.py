"""Quality gate, point in time (Codex QA F2): nothing recorded after the decision
time may pass, at the exact boundary it does, and missing timestamps fail."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from edge_api.config import Settings
from edge_api.services.quality import assess
from edge_ml.model import FEATURE_SET, MODEL_VERSION

DECISION = datetime(2026, 10, 16, tzinfo=UTC)
EARLIER = DECISION - timedelta(hours=1)
LATER = DECISION + timedelta(hours=1)


def _inputs(created=EARLIER, as_of=EARLIER, captured=EARLIER, finished=EARLIER):
    fixture = SimpleNamespace(status="scheduled", kickoff_at=DECISION + timedelta(hours=8))
    prediction = SimpleNamespace(
        id=1,
        created_at=created,
        input_data_as_of=as_of,
        model_version=SimpleNamespace(version=MODEL_VERSION, feature_set=FEATURE_SET),
        probability_home=0.6,
        probability_draw=0.2,
        probability_away=0.2,
        odds_snapshot=SimpleNamespace(captured_at=captured),
        features={"matches_home": 30, "matches_away": 30},
    )
    return fixture, prediction, SimpleNamespace(finished_at=finished)


def _failed(**times) -> set[str]:
    fixture, prediction, run = _inputs(**times)
    report = assess(fixture, prediction, now=DECISION, settings=Settings(), last_run=run)
    return {c.name for c in report.failed}


def test_inputs_recorded_before_the_decision_pass():
    assert _failed() == set()


def test_inputs_recorded_exactly_at_the_decision_pass():
    assert _failed(created=DECISION, as_of=DECISION, captured=DECISION, finished=DECISION) == set()


def test_everything_recorded_after_the_decision_fails():
    """Codex reproduction: all four timestamps one hour after the decision."""
    assert _failed(created=LATER, as_of=LATER, captured=LATER, finished=LATER) == {
        "prediction_timely",
        "odds_fresh",
        "ingestion_recent",
    }


@pytest.mark.parametrize(
    ("field", "check"),
    [
        ("created", "prediction_timely"),
        ("as_of", "prediction_timely"),
        ("captured", "odds_fresh"),
        ("finished", "ingestion_recent"),
    ],
)
def test_each_later_timestamp_fails_on_its_own(field, check):
    assert _failed(**{field: LATER}) == {check}


@pytest.mark.parametrize(
    ("field", "check"),
    [
        ("created", "prediction_timely"),
        ("as_of", "prediction_timely"),
        ("captured", "odds_fresh"),
        ("finished", "ingestion_recent"),
    ],
)
def test_a_missing_timestamp_fails_closed(field, check):
    assert _failed(**{field: None}) == {check}


def test_stale_inputs_still_fail():
    old = DECISION - timedelta(days=30)
    assert _failed(captured=old, finished=old) == {"odds_fresh", "ingestion_recent"}


def test_the_detail_says_when_an_input_is_from_after_the_decision():
    fixture, prediction, run = _inputs(finished=LATER)
    report = assess(fixture, prediction, now=DECISION, settings=Settings(), last_run=run)
    detail = next(c.detail for c in report.checks if c.name == "ingestion_recent")
    assert "after the decision time" in detail
