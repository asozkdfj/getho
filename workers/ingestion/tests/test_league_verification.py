"""More leagues scored with the verified rule (research report only)."""

from edge_ingestion import league_verification as lv
from edge_ingestion.history import openfootball


def test_extra_leagues_do_not_overlap_the_verified_ones():
    codes = set(lv.EXTRA_LEAGUES)
    assert len(codes) == 11
    assert not codes & set(openfootball.LEAGUES)
    api = [lg.api_football_id for lg in lv.EXTRA_LEAGUES.values()]
    assert len(set(api)) == len(api)
    assert not set(api) & {lg.api_football_id for lg in openfootball.LEAGUES.values()}
    divisions = [lg.division for lg in lv.EXTRA_LEAGUES.values()]
    assert len(set(divisions)) == len(divisions)


def test_summary_reads_the_verdict_and_the_market_context():
    report = {
        "leagues": [
            {
                "code": "sc.1",
                "name": "Premiership",
                "country": "Scotland",
                "test_matches": 656,
                "gain_vs_base_rate": {"mean": 0.09, "ci_low": 0.06, "ci_high": 0.12},
                "verified": True,
                "selection": {"eligible": True},
                "models": {"production": {"log_loss": 0.9765}},
                "market_context": {"market": {"log_loss": 0.9568}},
            }
        ]
    }
    (row,) = lv.summary(report)
    assert row["verified"] and row["league"] == "Scotland - Premiership"
    assert row["market_ll"] == 0.9568 and row["gain_vs_base_rate"] == [0.09, 0.06, 0.12]


def test_coverage_needs_every_test_season_at_90_percent_of_a_usual_season():
    scotland = {
        "2018-19": 228,
        "2019-20": 179,
        "2020-21": 228,
        "2021-22": 228,
        "2022-23": 228,
        "2023-24": 228,
        "2024-25": 200,
        "2025-26": 228,
    }
    c = lv.coverage(scotland)
    assert c["usual_season_matches"] == 228
    assert c["test_season_coverage"]["2024-25"] == round(200 / 228, 4)
    assert not c["eligible"] and "2024-25" in c["reason"]
    complete = {**scotland, "2024-25": 228}
    assert lv.coverage(complete)["eligible"]


def test_a_tie_takes_the_larger_usual_season():
    counts = {"2021-22": 380, "2022-23": 380, "2023-24": 306, "2024-25": 306, "2025-26": 345}
    c = lv.coverage(counts)
    assert c["usual_season_matches"] == 380
    assert not c["eligible"]  # 306 / 380 < 0.9


def test_a_missing_test_season_is_not_eligible():
    assert not lv.coverage({"2022-23": 380, "2023-24": 380, "2024-25": 380})["eligible"]
