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
                "models": {"production": {"log_loss": 0.9765}},
                "market_context": {"market": {"log_loss": 0.9568}},
            }
        ]
    }
    (row,) = lv.summary(report)
    assert row["verified"] and row["league"] == "Scotland - Premiership"
    assert row["market_ll"] == 0.9568 and row["gain_vs_base_rate"] == [0.09, 0.06, 0.12]
