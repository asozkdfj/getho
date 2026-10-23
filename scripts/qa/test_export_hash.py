import hashlib
import json

from edge_api.config import Settings
from edge_ingestion import cli
from edge_ingestion.providers import MockProvider


def test_export_manifest_hash_matches_written_bytes(now, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(data_provider="mock"))
    provider = MockProvider(now)
    league = provider.get_leagues()[0]
    year = str(int(provider.get_league_history(league)[0].season[:4]))
    target = tmp_path / "lineups.csv"
    assert (
        cli.main(
            [
                "export-lineups",
                "--leagues",
                league.provider_id,
                "--seasons",
                year,
                "--out",
                str(target),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert summary["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
