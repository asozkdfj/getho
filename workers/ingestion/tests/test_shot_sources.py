"""API-Football vs football-data.co.uk shots on target on the same matches."""

import json
from datetime import UTC, date, datetime

from edge_api.db.models import Fixture, League, MatchStatistic, Team
from edge_ingestion import cli
from edge_ingestion.shot_sources import _similarity, compare_shot_sources, season_of

NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)
CSV = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HS,AS,HST,AST
E0,04/10/2026,15:00,Man United,Chelsea,2,1,14,9,6,3
E0,04/10/2026,15:00,Arsenal,Everton,2,1,18,5,8,1
E0,05/10/2026,16:30,Liverpool,Spurs,0,0,10,10,3,4
"""


def _setup(s):
    league = League(
        provider="api_football",
        provider_id="39",
        name="Premier League",
        country="England",
        type="league",
    )
    s.add(league)
    s.flush()
    names = ["Manchester United", "Chelsea", "Arsenal", "Everton", "Liverpool", "Tottenham"]
    teams = {}
    for i, n in enumerate(names):
        teams[n] = Team(provider="api_football", provider_id=str(i), name=n, short_name=n[:3])
        s.add(teams[n])
    s.flush()

    def fixture(pid, home, away, hs, as_, day, stats):
        f = Fixture(
            provider="api_football",
            provider_id=pid,
            league_id=league.id,
            season="2026",
            kickoff_at=day,
            home_team_id=teams[home].id,
            away_team_id=teams[away].id,
            status="finished",
            home_score=hs,
            away_score=as_,
        )
        s.add(f)
        s.flush()
        for team, (shots, sot) in zip((home, away), stats, strict=True):
            s.add(
                MatchStatistic(
                    fixture_id=f.id,
                    team_id=teams[team].id,
                    provider="api_football",
                    shots=shots,
                    shots_on_target=sot,
                    expected_goals=None,
                    source="ingest",
                )
            )
        return f

    kick = datetime(2026, 10, 4, 14, tzinfo=UTC)
    fixture("1", "Manchester United", "Chelsea", 2, 1, kick, [(14, 6), (9, 3)])  # same numbers
    fixture("2", "Arsenal", "Everton", 2, 1, kick, [(18, 7), (5, 1)])  # SOT off by one
    fixture(
        "3",
        "Liverpool",
        "Tottenham",
        1,
        1,
        datetime(2026, 10, 5, 15, 30, tzinfo=UTC),
        [(10, 3), (10, 4)],
    )  # score differs from the file: unmatched
    s.flush()


def test_same_matches_are_joined_and_agreement_reported(db_session, tmp_path):
    _setup(db_session)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "football-data-2627-E0.csv").write_text(CSV)
    report = compare_shot_sources(db_session, "api_football", now=NOW, days=30, cache_dir=cache)
    assert report["counts"]["E0"] == {"with_api_stats": 3, "matched": 2, "unmatched": 1}
    sot = report["all"]["shots_on_target"]
    assert sot["n"] == 4
    assert sot["share_equal"] == 0.75
    assert sot["mean_abs_diff"] == 0.25
    assert sot["ratio"] == (6 + 3 + 7 + 1) / (6 + 3 + 8 + 1)
    assert report["all"]["shots"]["share_equal"] == 1.0


def test_names_and_seasons():
    assert _similarity("Manchester United", "Man United") >= 0.5
    assert _similarity("Tottenham", "Spurs") < 0.5  # a name pair the score key must carry
    assert season_of(date(2026, 10, 4)) == "2026-27"
    assert season_of(date(2027, 5, 4)) == "2026-27"


def test_cli_prints_the_report(db_session, tmp_path, capsys, monkeypatch):
    from contextlib import contextmanager

    _setup(db_session)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "football-data-2627-E0.csv").write_text(CSV)

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(cli, "session_scope", same_session)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: type("S", (), {"data_provider": "api_football", "log_level": "INFO"})(),
    )
    argv = ["compare-shots", "--days", "30", "--cache-dir", str(cache), "--now", NOW.isoformat()]
    assert cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["E0"]["matched"] == 2
