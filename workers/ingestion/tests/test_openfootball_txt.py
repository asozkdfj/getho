from datetime import UTC, datetime

from edge_ingestion.history.openfootball_txt import parse, team_key

CUP = """= English FA Cup 2023/24

# Date       Fri Nov 3 2023 - Sat May 25 2024 (204d)

▪ Round 1
  Fri Nov 3 2023
    19:45  Barnsley FC             v Horsham FC               3-3 (2-2)
  Sat Dec 30
    15:00  Arsenal FC              v Liverpool FC             0-2 (0-0)
  Sun Jan 7
           Wolverhampton Wanderers v Brentford FC             3-2 a.e.t. (2-2, 1-1)
           Postponed FC            v Somebody FC              -
"""

EUROPE = """= UEFA Champions League 2023/24
▪ Group, Matchday 1
  Tue Sep 19 2023
    21:00  Racing Club de Lens (FRA) v Arsenal FC (ENG)         2-1 (1-1)
"""


def test_parses_dates_times_and_extra_time():
    matches = parse(CUP, "facup", "2023-24")
    assert [(m.home, m.away) for m in matches] == [
        ("Barnsley", "Horsham"),
        ("Arsenal", "Liverpool"),
        ("Wolverhampton Wanderers", "Brentford"),
    ]
    assert matches[0].kickoff_at == datetime(2023, 11, 3, 19, 45, tzinfo=UTC)
    # the year rolls over without an explicit year; the time carries over
    assert matches[2].kickoff_at == datetime(2024, 1, 7, 15, 0, tzinfo=UTC)
    assert [m.extra_time for m in matches] == [False, False, True]


def test_european_names_match_the_league_files():
    (m,) = parse(EUROPE, "cl", "2023-24")
    assert (m.home, m.away) == ("Racing Club de Lens", "Arsenal")
    assert m.kickoff_at == datetime(2023, 9, 19, 19, 0, tzinfo=UTC)  # 21:00 CEST
    assert team_key("Manchester City FC (ENG)") == "Manchester City"
