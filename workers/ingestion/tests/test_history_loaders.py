from datetime import UTC, datetime

from edge_ingestion.history.football_data import parse_csv
from edge_ingestion.history.openfootball import (
    normalize_team,
    parse_season,
    season_labels,
    validate_season,
)


def test_normalize_team_merges_spelling_variants():
    assert (
        normalize_team("Manchester City FC")
        == normalize_team("Manchester City")
        == "Manchester City"
    )
    assert normalize_team("AFC Bournemouth") == "Bournemouth"
    assert normalize_team("Sunderland AFC") == "Sunderland"


def test_season_labels():
    assert season_labels("2018-19", "2020-21") == ["2018-19", "2019-20", "2020-21"]


def test_parse_openfootball_handles_both_score_shapes_and_uk_time():
    payload = {
        "matches": [
            {
                "date": "2025-08-16",
                "time": "12:30",
                "team1": "Aston Villa FC",
                "team2": "Newcastle United FC",
                "score": [0, 0],
            },
            {
                "date": "2024-01-13",
                "time": "15:00",
                "team1": "A FC",
                "team2": "B",
                "score": {"ft": [2, 1], "ht": [1, 0]},
            },
            {"date": "2026-05-24", "team1": "C", "team2": "D"},  # not played -> skipped
        ]
    }
    ms = parse_season(payload, "2025-26")
    assert len(ms) == 2
    # 12:30 BST (UTC+1) -> 11:30 UTC ; 15:00 GMT (UTC+0) -> 15:00 UTC
    assert ms[0].result.kickoff_at == datetime(2025, 8, 16, 11, 30, tzinfo=UTC)
    assert ms[1].result.kickoff_at == datetime(2024, 1, 13, 15, 0, tzinfo=UTC)
    assert (ms[0].result.home, ms[1].result.home_goals) == ("Aston Villa", 2)
    assert all(m.result.season == "2025-26" and m.odds is None for m in ms)


def test_validate_season_flags_incomplete_data():
    ms = parse_season(
        {"matches": [{"date": "2024-01-13", "team1": "A", "team2": "B", "score": [1, 0]}]}, "x"
    )
    problems = validate_season(ms, "x")
    assert any("20 teams" in p for p in problems) and any("incomplete" in p for p in problems)


def test_football_data_csv_prefers_closing_pinnacle_odds(tmp_path):
    csv = tmp_path / "2024-25.csv"
    csv.write_text(
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A,PSCH,PSCD,PSCA\n"
        "E0,16/08/2024,20:00,Man United,Fulham,1,0,1.60,4.20,5.25,1.65,4.10,5.60\n"
        "E0,17/08/2024,12:30,Ipswich,Liverpool,0,2,5.50,4.50,1.55,,,\n"
    )
    ms = parse_csv(csv, "2024-25")
    assert ms[0].odds == (1.65, 4.10, 5.60)  # Pinnacle closing
    assert ms[1].odds == (5.50, 4.50, 1.55)  # falls back to Bet365 opening
    assert ms[0].result.kickoff_at == datetime(2024, 8, 16, 19, 0, tzinfo=UTC)
