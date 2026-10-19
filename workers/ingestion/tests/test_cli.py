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
    assert report["leagues"] == 4 and report["leagues_by_type"] == {"league": 3, "cup": 1}
    assert report["leagues_with_odds"] == 3
    assert report["fixtures_last_and_next_24h"] == sum(report["fixture_statuses"].values())
    assert report["bookmakers"] in ([], ["bet365", "pinnacle"])
    assert report["requests_used"] == len(fake.calls) <= 10
    assert report["requests_left_today"] == 7400
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


def test_main_prints_check_provider_report_as_json(monkeypatch, capsys):
    """End-to-end through main(): the report (with datetimes) must serialise."""
    provider = ApiFootballProvider(
        "k",
        reference_time=REF,
        transport=FakeApiFootball(),
        min_interval_seconds=0,
        sleep=lambda _: None,
    )
    monkeypatch.setattr(cli, "get_provider", lambda *a, **kw: provider)
    monkeypatch.setattr(cli, "configure_logging", lambda *_: None)
    assert cli.main(["check-provider", "--now", "2026-10-15T09:00:00Z"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["result"]["leagues"] == 4
    sample = out["result"]["sample_finished_fixture"]
    assert sample is None or sample["kickoff_at"].startswith("2026-")


def test_code_fingerprint_command_prints_the_build_identity(capsys):
    from edge_api.versioning import build_info

    assert cli.main(["code-fingerprint"]) == 0
    assert json.loads(capsys.readouterr().out) == build_info()


def test_check_xg_reports_which_leagues_return_expected_goals():
    from edge_ingestion.testing import LEAGUE, XG_LEAGUES

    fake = FakeApiFootball()
    p = ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )
    settings = Settings(data_provider="api_football", api_football_key="k")
    import edge_ingestion.cli as cli_module

    original = cli_module.get_provider
    cli_module.get_provider = lambda *a, **k: p
    try:
        report = cli.check_xg(settings, REF, days=7, limit=40)
    finally:
        cli_module.get_provider = original
    assert report["fixtures_checked"] > 0 and report["leagues_checked"] >= 2
    assert {LEAGUE} == XG_LEAGUES
    assert report["leagues_with_xg"] == ["England - Premier League"]
    for name, row in report["per_league"].items():
        assert row["with_statistics"] == row["fixtures_checked"]
        if name == "England - Premier League":
            assert row["with_xg"] == row["fixtures_checked"] and row["sample_xg"] == [1.2, 1.3]
        else:
            assert row["with_xg"] == 0 and row["sample_xg"] is None
    # catalogue + one /fixtures call per day + details in batches of 20
    assert report["requests_used"] <= 1 + 8 + -(-40 // 20)


def test_match_statistics_skip_unreadable_values():
    from edge_ingestion.providers.api_football import _count, _number

    assert _count("12") == 12 and _count(None) is None and _count("-1") is None
    assert _number("1.37") == 1.37 and _number(None) is None and _number("nan") is None
