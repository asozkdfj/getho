from datetime import UTC, datetime, timedelta

from scripts.qa.audit_decision_market import available, metrics, valid_probabilities


def test_backfilled_snapshot_is_not_available():
    decision = datetime(2026, 10, 19, tzinfo=UTC)
    assert not available(decision + timedelta(seconds=1), decision - timedelta(hours=1), decision)
    assert not available(decision - timedelta(hours=1), decision + timedelta(seconds=1), decision)
    assert available(decision, decision, decision)


def test_invalid_probabilities_and_empty_sample():
    assert valid_probabilities([0.6, 0.2, 0.2])
    for p in ([float("nan"), 0.5, 0.5], [-0.1, 0.6, 0.5], [0.5, 0.5, 0.5]):
        assert not valid_probabilities(p)
    assert metrics([], "production") is None
