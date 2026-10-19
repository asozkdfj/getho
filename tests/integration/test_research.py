"""Private research view (/research): collection health, shadow-v1 progress
without scores until final, live CLV."""

from edge_api.api.routes.research import _shadow


def test_research_endpoint_returns_every_section(client):
    res = client.get("/research?days=3")
    assert res.status_code == 200
    body = res.json()
    assert body["is_demo"] is True and body["provider"] == "mock"
    assert len(body["collection"]["days"]) == 3
    shadow = body["shadow"]
    assert shadow["protocol"] == "shadow-v1" and shadow["min_settled"] == 1500
    assert shadow["status"] == "provisional" and shadow["decisions"] is None
    assert body["live_clv"]["analysed"] == 0  # nothing kicked off in the window yet
    assert "log_loss" not in res.text  # no score of any kind while provisional


def test_shadow_scores_are_withheld_until_the_report_is_final():
    report = {
        "protocol": "shadow-v1",
        "window": {"start": "2026-10-20", "end": "2026-12-14"},
        "status": "provisional",
        "recorded": 900,
        "excluded": {},
        "settled": 800,
        "pending": 100,
        "not_played": 0,
        "metrics": {"n": 800, "production": {"log_loss": 0.99}},
        "decisions": {},
        "coverage_days": {"with_records": 20, "no_decision": []},
        "decision_timing": {"minutes_after_publish_hour": {"median": 12}},
    }
    assert _shadow(report).decisions is None
    final = _shadow(report | {"status": "final", "decisions": {"market_beats_production": True}})
    assert final.decisions == {
        "decisions": {"market_beats_production": True},
        "metrics": report["metrics"],
    }


def test_days_parameter_is_bounded(client):
    assert client.get("/research?days=0").status_code == 422
    assert client.get("/research?days=32").status_code == 422
