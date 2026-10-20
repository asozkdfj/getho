"""Collection quality per pick day (outcome-blind)."""

import json
from datetime import timedelta

from edge_api.db.models import IngestionRun
from edge_api.services import queries
from edge_api.services.collection_quality import quality_report
from edge_api.services.picks import local_day, publish_daily_pick
from edge_api.services.shadow import market_odds_at
from tests.integration.test_picks import settings

INTERVAL = timedelta(minutes=30)


def test_report_covers_runs_decision_and_inputs(session_factory, seeded, now):
    s_ = settings()
    with session_factory() as s:
        pick = publish_daily_pick(s, s_, now)  # 18:00 KST: decided 9 h after the publish hour
        day = pick.pick_date
        s.add(
            IngestionRun(
                provider="mock",
                started_at=now + timedelta(hours=1),
                finished_at=now + timedelta(hours=1),
                status="failed",
                error="ProviderError: quota",
            )
        )
        s.flush()
        report = quality_report(
            s, s_, day - timedelta(days=1), day, now=now + timedelta(hours=2), interval=INTERVAL
        )
        before, today = report["days"]
        assert before["decision"]["decided"] is False and before["runs"]["success"] == 0
        assert (
            today["decision"]["decided"] and today["decision"]["minutes_after_publish_hour"] == 540
        )
        assert today["runs"]["success"] == 1 and today["runs"]["failed"] == 1
        assert today["runs"]["errors"] == ["ProviderError: quota"]
        # 09:00 KST (window start) to the only successful run at 18:00 KST
        assert today["runs"]["longest_gap_hours"] == 9.0
        assert today["runs"]["expected"] == int(timedelta(hours=11) / INTERVAL)

        ld = local_day(now, s_)
        fixtures = [
            f
            for f in queries.fixtures_between(s, ld.start_utc, ld.end_utc, "mock")
            if f.kickoff_at > now
        ]
        ids = [f.id for f in fixtures]
        preds = queries.latest_predictions_by_fixture(s, ids, as_of=now)
        assert today["fixtures_at_decision"] == len(fixtures) > 0
        assert today["with_prediction"] == len([p for p in preds.values() if p.created_at <= now])
        assert today["with_odds"] == len(market_odds_at(s, ids, s_.bookmaker, now))
        assert sum(c["fixtures"] for c in today["leagues"]) <= len(fixtures)
        keys = {"league_id", "provider_id", "country", "name"}
        assert all(keys <= set(c) for c in today["leagues"])
        assert today["shadow"]["recorded"] + today["shadow"]["excluded"] == len(
            queries.fixtures_between(s, ld.start_utc, ld.end_utc, "mock")
        )
        a = today["player_info"]["absences"]
        assert (
            a["reported"] + a["none_reported"] + a["unknown"] == 2 * today["fixtures_at_decision"]
        )

        summary = report["summary"]
        assert summary["days_without_decision"] == [before["day"]]
        assert summary["days_with_failed_runs"] == [today["day"]]
        assert today["day"] in summary["days_with_long_gaps"]
        assert 0 <= summary["prediction_share"] <= 1 and 0 <= summary["odds_share"] <= 1
        keys = _keys(report)
        assert not keys & {"hit", "log_loss", "brier", "home_score", "actual_outcome"}


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_cli_prints_the_report(session_factory, seeded, now, monkeypatch, capsys):
    from contextlib import contextmanager

    from edge_api.config import get_settings
    from edge_ingestion import cli

    @contextmanager
    def scope():
        with session_factory() as s:
            yield s

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setenv("DATA_PROVIDER", "mock")
    get_settings.cache_clear()
    day = now.date().isoformat()
    assert cli.main(["collection-quality", "--start", day, "--end", day]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["days"] == 1 and report["expected_interval_minutes"] == 30
    get_settings.cache_clear()


def test_leagues_sharing_a_name_are_counted_apart(monkeypatch):
    """Grouped by league id, not the display name (Codex CQ-1)."""
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from edge_api.config import Settings
    from edge_api.services import collection_quality as quality

    at = datetime(2026, 10, 19, tzinfo=UTC)
    fixtures = [
        SimpleNamespace(
            id=i,
            league_id=i,
            kickoff_at=at + timedelta(hours=2),
            league=SimpleNamespace(provider_id=str(38 + i), name="Premier League", country=c),
        )
        for i, c in ((1, "England"), (2, "Kenya"))
    ]
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    session.execute.return_value.all.return_value = []
    monkeypatch.setattr(quality, "_runs", lambda *a: {})
    monkeypatch.setattr(quality.queries, "fixtures_between", lambda *a: fixtures)
    monkeypatch.setattr(quality.queries, "latest_predictions_by_fixture", lambda *a, **k: {})
    monkeypatch.setattr(quality, "market_odds_at", lambda *a: {})
    monkeypatch.setattr(
        quality,
        "coverage_on",
        lambda *a, **k: {"absences": {}, "lineups_in": 0, "regulars_known": 0},
    )
    report = quality.quality_on(
        session, Settings(data_provider="mock"), at.date(), now=at, interval=INTERVAL
    )
    assert [(c["country"], c["fixtures"]) for c in report["leagues"]] == [
        ("England", 1),
        ("Kenya", 1),
    ]
