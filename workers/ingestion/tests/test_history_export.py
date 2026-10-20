"""`edge export-match-stats`: past seasons' statistics to CSV from the provider only."""

import csv
import io
import json

from edge_ingestion import cli
from edge_ingestion.history_export import COLUMNS, export_match_stats
from edge_ingestion.providers import ApiFootballProvider, MockProvider
from edge_ingestion.testing import REF, FakeApiFootball


def test_mock_export_writes_one_row_per_finished_fixture(now):
    provider = MockProvider(now)
    league = provider.get_leagues()[0]
    year = int(provider.get_league_history(league)[0].season[:4])
    result = export_match_stats(provider, [league.provider_id], [year])
    rows = list(csv.DictReader(io.StringIO(result.csv())))
    counts = result.per_season[f"{league.provider_id} {year}"]
    assert rows and len(rows) == counts["finished"]
    assert tuple(rows[0]) == COLUMNS
    assert counts["with_xg"] == counts["with_statistics"] == len(rows)
    assert all(float(r["home_xg"]) >= 0 and int(r["home_goals"]) >= 0 for r in rows)
    assert [r["kickoff_at"] for r in rows] == sorted(r["kickoff_at"] for r in rows)


def test_missing_statistics_stay_empty(now, monkeypatch):
    provider = MockProvider(now)
    league = provider.get_leagues()[0]
    year = int(provider.get_league_history(league)[0].season[:4])
    monkeypatch.setattr(provider, "get_match_statistics", lambda ids: [])
    result = export_match_stats(provider, [league.provider_id], [year])
    row = next(csv.DictReader(io.StringIO(result.csv())))
    assert row["home_xg"] == "" and row["home_sot"] == ""
    assert result.per_season[f"{league.provider_id} {year}"]["with_statistics"] == 0


def test_api_football_reads_the_season_and_its_details():
    fake = FakeApiFootball()
    provider = ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )
    league = next(lg for lg in provider.get_leagues() if lg.provider_id == "39")
    result = export_match_stats(provider, ["39"], [2025])
    calls = [(path, params) for path, params, _ in fake.calls]
    assert ("/fixtures", {"league": "39", "season": "2025", "timezone": "UTC"}) in calls
    assert any(path == "/fixtures" and "ids" in params for path, params in calls)
    counts = result.per_season["39 2025"]
    assert counts["finished"] > 0 and counts["with_statistics"] > 0
    assert league.provider_id == "39"


def test_cli_writes_csv_to_stdout_and_the_summary_to_stderr(now, capsys, monkeypatch):
    from edge_api.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(data_provider="mock"))
    provider = MockProvider(now)
    league = provider.get_leagues()[0]
    year = int(provider.get_league_history(league)[0].season[:4])
    args = ["export-match-stats", "--leagues", league.provider_id, "--seasons", str(year)]
    assert cli.main(args) == 0
    out, err = capsys.readouterr()
    assert out.startswith(",".join(COLUMNS))
    summary = json.loads(err.strip().splitlines()[-1])
    assert summary["per_season"][f"{league.provider_id} {year}"]["finished"] > 0
