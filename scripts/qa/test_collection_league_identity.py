"""Independent regression: equal display names must not merge distinct leagues."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from edge_api.config import Settings
from edge_api.services import collection_quality as quality


def test_same_name_leagues_remain_separate(monkeypatch):
    at = datetime(2026, 10, 19, tzinfo=UTC)
    fixtures = [
        SimpleNamespace(
            id=i,
            league_id=i,
            kickoff_at=at + timedelta(hours=2),
            league=SimpleNamespace(id=i, name="Premier League", country=country),
        )
        for i, country in ((1, "England"), (2, "Kenya"))
    ]
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    session.execute.return_value.all.return_value = []
    monkeypatch.setattr(quality, "_runs", lambda *args: {})
    monkeypatch.setattr(quality.queries, "fixtures_between", lambda *args: fixtures)
    monkeypatch.setattr(quality.queries, "latest_predictions_by_fixture", lambda *a, **k: {})
    monkeypatch.setattr(quality, "market_odds_at", lambda *args: {})
    monkeypatch.setattr(
        quality,
        "coverage_on",
        lambda *a, **k: {
            "absences": {},
            "lineups_in": 0,
            "regulars_known": 0,
        },
    )
    report = quality.quality_on(
        session, Settings(data_provider="mock"), at.date(), now=at, interval=timedelta(minutes=30)
    )
    assert len(report["leagues"]) == 2, report["leagues"]
