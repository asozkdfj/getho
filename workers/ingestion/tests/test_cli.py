import json

from edge_api.config import Settings
from edge_ingestion import cli
from edge_ingestion.providers import ApiFootballProvider
from edge_ingestion.testing import REF, FakeApiFootball


def test_check_provider_reports_quota_and_parse_counts(monkeypatch):
    fake = FakeApiFootball()
    provider = ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )
    monkeypatch.setattr(cli, "get_provider", lambda *a, **kw: provider)
    report = cli.check_provider(Settings(data_provider="api_football", api_football_key="k"), REF)
    assert report["provider"] == "api_football"
    assert report["account"]["plan"] == "Free"
    assert report["seasons"] == [2025, 2026]
    assert report["teams"] == 21
    assert report["fixtures_with_primary_bookmaker_odds"] == report["upcoming_14d"] > 0
    assert report["bookmakers"] == ["bet365", "pinnacle"]
    assert report["requests_used"] == len(fake.calls) <= 8
    assert "k" not in json.dumps(report["account"])


def test_cli_fails_cleanly_without_api_key(monkeypatch, capsys):
    monkeypatch.setenv("DATA_PROVIDER", "api_football")
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    cli.get_settings.cache_clear()
    try:
        assert cli.main(["check-provider"]) == 2
    finally:
        cli.get_settings.cache_clear()
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "API_FOOTBALL_KEY" in err["error"]
