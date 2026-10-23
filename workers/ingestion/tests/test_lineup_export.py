"""`edge export-lineups`: past seasons' line-ups and minutes to CSV, provider only."""

import csv
import io
import json

from edge_ingestion import cli
from edge_ingestion.lineup_export import COLUMNS, export_lineups
from edge_ingestion.providers import ApiFootballProvider, MockProvider
from edge_ingestion.testing import REF, FakeApiFootball


def _season(provider):
    league = provider.get_leagues()[0]
    return league, int(provider.get_league_history(league)[0].season[:4])


def _rows(result):
    return list(csv.DictReader(io.StringIO(result.csv())))


def test_mock_export_writes_every_player_of_every_finished_fixture(now):
    provider = MockProvider(now)
    league, year = _season(provider)
    result = export_lineups(provider, [league.provider_id], [year])
    rows = _rows(result)
    counts = result.per_season[f"{league.provider_id} {year}"]
    assert tuple(rows[0]) == COLUMNS
    fixtures = {r["fixture_id"] for r in rows}
    assert len(fixtures) == counts["finished"] > 0
    assert counts["with_sheets"] == counts["full_xi"] == counts["finished"]
    by_team: dict[tuple[str, str], int] = {}
    for r in rows:
        assert r["team_id"] in (r["home_id"], r["away_id"])
        by_team[(r["fixture_id"], r["team_id"])] = by_team.get(
            (r["fixture_id"], r["team_id"]), 0
        ) + int(r["started"])
    assert set(by_team.values()) == {11}
    assert [r["kickoff_at"] for r in rows] == sorted(r["kickoff_at"] for r in rows)


def test_fixtures_without_details_keep_their_result_and_empty_players(now, monkeypatch):
    provider = MockProvider(now)
    league, year = _season(provider)
    monkeypatch.setattr(provider, "get_appearances", lambda ids: [])
    result = export_lineups(provider, [league.provider_id], [year])
    rows = _rows(result)
    counts = result.per_season[f"{league.provider_id} {year}"]
    assert len(rows) == counts["finished"] and counts["with_sheets"] == 0
    assert all(r["player_id"] == "" and r["minutes"] == "" for r in rows)
    assert all(r["home_goals"] != "" for r in rows)  # results are never dropped


def test_api_football_reads_the_season_and_its_details():
    fake = FakeApiFootball()
    provider = ApiFootballProvider(
        "k", reference_time=REF, transport=fake, min_interval_seconds=0, sleep=lambda _: None
    )
    result = export_lineups(provider, ["39"], [2025])
    calls = [(path, params) for path, params, _ in fake.calls]
    assert ("/fixtures", {"league": "39", "season": "2025", "timezone": "UTC"}) in calls
    assert any(path == "/fixtures" and "ids" in params for path, params in calls)
    counts = result.per_season["39 2025"]
    assert counts["finished"] > 0 and counts["with_sheets"] > 0
    assert any(r["player_id"] and r["started"] == "1" for r in _rows(result))


def test_cli_writes_csv_to_stdout_and_the_summary_to_stderr(now, capsys, monkeypatch):
    from edge_api.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(data_provider="mock"))
    league, year = _season(MockProvider(now))
    args = ["export-lineups", "--leagues", league.provider_id, "--seasons", str(year)]
    assert cli.main(args) == 0
    out, err = capsys.readouterr()
    assert out.startswith(",".join(COLUMNS))
    summary = json.loads(err.strip().splitlines()[-1])
    assert summary["per_season"][f"{league.provider_id} {year}"]["finished"] > 0
    assert len(summary["sha256"]) == 64


def test_summary_hash_matches_the_written_file(now, tmp_path, capsys, monkeypatch):
    """Codex QA EXPORT-HASH-1: hash the exact bytes written (no CRLF rewrite)."""
    import hashlib

    from edge_api.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(data_provider="mock"))
    league, year = _season(MockProvider(now))
    target = tmp_path / "lineups.csv"
    args = ["export-lineups", "--leagues", league.provider_id, "--seasons", str(year)]
    assert cli.main([*args, "--out", str(target)]) == 0
    summary = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    data = target.read_bytes()
    assert summary["sha256"] == hashlib.sha256(data).hexdigest()
    assert b"\r\n" not in data
