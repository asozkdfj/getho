from datetime import UTC, date, datetime

from edge_ingestion.history.club_match_data import parse, season_labels, team_key

CSV = """Division,MatchDate,MatchTime,HomeTeam,AwayTeam,FTHome,FTAway,OddHome,OddDraw,OddAway
E0,2020-07-26,16:00:00,Chelsea,Wolves,2.0,0.0,1.5,4.2,6.0
E0,2020-09-12,12:30:00,Fulham,Arsenal,0.0,3.0,5.0,3.9,1.7
E0,2020-09-12,,Liverpool,Leeds,4.0,3.0,1.2,7.0,13.0
E0,2020-09-13,16:30:00,Spurs,Everton,,,2.0,3.5,3.8
D1,2020-09-18,19:30:00,Bayern Munich,Schalke 04,8.0,0.0,1.1,11.0,21.0
E0,2020-09-19,15:00:00,Leeds,Fulham,4.0,3.0,1.0,3.5,3.8
"""


def test_parse_keeps_one_division_and_played_matches():
    matches = parse(CSV, "E0")
    assert [(m.result.home, m.result.away) for m in matches] == [
        ("chelsea", "wolves"),
        ("fulham", "arsenal"),
        ("liverpool", "leeds"),
        ("leeds", "fulham"),
    ]
    # UK summer time: 12:30 BST is 11:30 UTC; a missing time means 15:00 local
    assert matches[1].result.kickoff_at == datetime(2020, 9, 12, 11, 30, tzinfo=UTC)
    assert matches[2].result.kickoff_at == datetime(2020, 9, 12, 14, 0, tzinfo=UTC)
    assert matches[1].odds == (5.0, 3.9, 1.7)
    assert matches[3].odds is None  # an odd of 1.0 is not a real price


def test_season_labels_rules():
    days = [
        date(2019, 8, 9),
        date(2020, 3, 9),
        date(2020, 6, 17),  # COVID restart after > 30 days, but in June: same season
        date(2020, 7, 1),
        date(2020, 7, 26),
        date(2020, 9, 12),  # new season
        date(2022, 11, 13),
        date(2022, 12, 26),  # World Cup break restart in December: same season
    ]
    assert season_labels(days) == [
        "2019-20",
        "2019-20",
        "2019-20",
        "2019-20",
        "2019-20",
        "2020-21",
        "2020-21",
        "2020-21",
    ]


def test_team_spellings_collapse():
    assert team_key("Nott'm Forest") == team_key("Nottm Forest")
    assert team_key("M'gladbach") == team_key("MGladbach")
    assert team_key("Preußen Münster") == team_key("Preussen Munster")
    assert team_key("Man United") != team_key("Man City")


def test_quarter_lines_are_restored():
    from edge_ingestion.history.club_match_data import restore_quarter_line

    assert restore_quarter_line(-0.3) == -0.25 and restore_quarter_line(-0.8) == -0.75
    assert restore_quarter_line(1.3) == 1.25 and restore_quarter_line(0.8) == 0.75
    assert restore_quarter_line(-0.25) == -0.25 and restore_quarter_line(-1.5) == -1.5
    assert restore_quarter_line(0.0) == 0.0 and restore_quarter_line(-2.0) == -2.0
    assert restore_quarter_line(-0.4) is None  # not a handicap line


def test_goal_market_odds_are_keyed_like_matches(tmp_path):
    from edge_ingestion.history.club_match_data import CACHE_NAME, load_goal_odds, match_key

    text = (
        "Division,MatchDate,MatchTime,HomeTeam,AwayTeam,FTHome,FTAway,OddHome,OddDraw,OddAway,"
        "Over25,Under25,HandiSize,HandiHome,HandiAway\n"
        "E0,2020-09-12,12:30:00,Fulham,Arsenal,0.0,3.0,5.0,3.9,1.7,1.8,2.0,0.8,1.9,1.95\n"
        "E0,2020-09-19,15:00:00,Leeds,Fulham,4.0,3.0,2.0,3.5,3.8,,,x,1.9,1.9\n"
    )
    (tmp_path / CACHE_NAME).write_text(text)
    odds = load_goal_odds("en.1", tmp_path)
    fulham = next(m for m in parse(text, "E0") if m.result.home == "fulham")
    o = odds[match_key(fulham.result)]
    assert (o.over25, o.under25) == (1.8, 2.0)
    assert (o.handicap, o.handicap_home, o.handicap_away) == (0.75, 1.9, 1.95)
    leeds = next(m for m in parse(text, "E0") if m.result.home == "leeds")
    o = odds[match_key(leeds.result)]
    assert o.over25 is None and o.handicap is None  # missing / malformed
