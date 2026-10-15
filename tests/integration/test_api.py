import pytest

from edge_ml.value import expected_value


def _upcoming_with_prediction(client, n):
    data = client.get("/fixtures", params={"days": 7}).json()
    out, teams = [], set()
    for f in data["fixtures"]:
        pair = {f["home_team"]["id"], f["away_team"]["id"]}
        if f["status"] == "scheduled" and f["prediction_id"] and not pair & teams:
            out.append(f)
            teams |= pair
    assert len(out) >= n
    return out[:n]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"


def test_list_fixtures_defaults_to_today_utc(client, now):
    r = client.get("/fixtures")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == now.date().isoformat()
    assert body["days"] == 1
    assert body["data_provider"] == "mock" and body["bookmaker"] == "mockbook"
    for f in body["fixtures"]:
        assert f["kickoff_at"].startswith(body["date"])
        assert f["kickoff_at"].endswith("Z")


def test_list_fixtures_week_and_timezone(client):
    week = client.get("/fixtures", params={"days": 7, "tz": "Asia/Seoul"}).json()
    assert week["tz"] == "Asia/Seoul"
    assert week["range_start_utc"].endswith("15:00:00Z")  # KST midnight == 15:00 UTC
    assert len(week["fixtures"]) >= 10
    kickoffs = [f["kickoff_at"] for f in week["fixtures"]]
    assert kickoffs == sorted(kickoffs)


def test_list_fixtures_explicit_date(client):
    body = client.get("/fixtures", params={"date": "2026-10-16"}).json()
    assert body["date"] == "2026-10-16"
    assert all(f["kickoff_at"].startswith("2026-10-16") for f in body["fixtures"])


@pytest.mark.parametrize(
    "params", [{"tz": "Mars/Base"}, {"days": 0}, {"days": 15}, {"date": "15-10-2026"}]
)
def test_list_fixtures_validation(client, params):
    assert client.get("/fixtures", params=params).status_code == 422


def test_fixture_summary_probabilities_sum_to_one(client):
    for f in client.get("/fixtures", params={"days": 7}).json()["fixtures"]:
        for key in ("model_probabilities", "fair_market_probabilities"):
            if f[key]:
                assert sum(f[key].values()) == pytest.approx(1.0, abs=1e-9)


def test_fixture_detail_and_404(client):
    fid = _upcoming_with_prediction(client, 1)[0]["id"]
    r = client.get(f"/fixtures/{fid}")
    assert r.status_code == 200
    body = r.json()
    history = body["odds_history"]
    assert history and body["latest_odds"] == history[-1]
    assert [h["captured_at"] for h in history] == sorted(h["captured_at"] for h in history)
    assert client.get("/fixtures/999999").status_code == 404
    assert client.get("/fixtures/999999/prediction").status_code == 404


def test_prediction_endpoint_math(client):
    fid = _upcoming_with_prediction(client, 1)[0]["id"]
    body = client.get(f"/fixtures/{fid}/prediction").json()
    assert sum(body["probabilities"].values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(body["fair_market_probabilities"].values()) == pytest.approx(1.0, abs=1e-12)
    assert body["overround"] > 0
    assert body["model"]["version"] and body["model"]["git_sha"]
    assert body["input_data_as_of"] and body["created_at"]
    assert "보장하지 않습니다" in body["disclaimer"]
    assert [o["outcome"] for o in body["outcomes"]] == ["HOME", "DRAW", "AWAY"]
    for o in body["outcomes"]:
        assert o["edge"] == pytest.approx(o["model_probability"] - o["fair_probability"])
        assert o["expected_value"] == pytest.approx(
            expected_value(o["model_probability"], o["decimal_odds"])
        )
        assert o["exceeds_threshold"] == (
            o["edge"] >= body["value_threshold"] and o["expected_value"] >= body["value_threshold"]
        )


def test_prediction_missing_for_finished_fixture(client):
    fixtures = client.get("/fixtures", params={"date": "2026-10-14"}).json()["fixtures"]
    finished = [f for f in fixtures if f["status"] == "finished"]
    assert finished
    assert client.get(f"/fixtures/{finished[0]['id']}/prediction").status_code == 404


@pytest.mark.parametrize("n_legs", [2, 3])
def test_combination_analyze(client, n_legs):
    fixtures = _upcoming_with_prediction(client, n_legs)
    outcomes = ["HOME", "DRAW", "AWAY"]
    payload = {
        "selections": [
            {"fixture_id": f["id"], "outcome": outcomes[i]} for i, f in enumerate(fixtures)
        ]
    }
    r = client.post("/combinations/analyze", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "independence_approximation"
    assert body["is_approximation"] is True
    assert any("독립" in n for n in body["notes"])
    p_model = p_fair = odds = 1.0
    for leg in body["legs"]:
        p_model *= leg["model_probability"]
        p_fair *= leg["fair_probability"]
        odds *= leg["decimal_odds"]
    assert body["model_probability"] == pytest.approx(p_model)
    assert body["fair_market_probability"] == pytest.approx(p_fair)
    assert body["combined_odds"] == pytest.approx(odds)
    assert body["expected_value"] == pytest.approx(p_model * odds - 1)
    assert body["edge"] == pytest.approx(p_model - p_fair)


def test_combination_rejects_same_fixture(client):
    fid = _upcoming_with_prediction(client, 1)[0]["id"]
    payload = {
        "selections": [
            {"fixture_id": fid, "outcome": "HOME"},
            {"fixture_id": fid, "outcome": "AWAY"},
        ]
    }
    r = client.post("/combinations/analyze", json=payload)
    assert r.status_code == 422 and "서로 다른 경기" in r.json()["detail"]


@pytest.mark.parametrize("n", [1, 4])
def test_combination_leg_count_validation(client, n):
    fixtures = client.get("/fixtures", params={"days": 7}).json()["fixtures"]
    payload = {"selections": [{"fixture_id": f["id"], "outcome": "HOME"} for f in fixtures[:n]]}
    assert client.post("/combinations/analyze", json=payload).status_code == 422


def test_combination_rejects_shared_team(client):
    data = client.get("/fixtures", params={"days": 14}).json()["fixtures"]
    upcoming = [f for f in data if f["status"] == "scheduled" and f["prediction_id"]]
    for i, a in enumerate(upcoming):
        for b in upcoming[i + 1 :]:
            if {a["home_team"]["id"], a["away_team"]["id"]} & {
                b["home_team"]["id"],
                b["away_team"]["id"],
            }:
                payload = {
                    "selections": [
                        {"fixture_id": a["id"], "outcome": "HOME"},
                        {"fixture_id": b["id"], "outcome": "HOME"},
                    ]
                }
                r = client.post("/combinations/analyze", json=payload)
                assert r.status_code == 422 and "같은 팀" in r.json()["detail"]
                return
    pytest.fail("seed data should contain two upcoming fixtures sharing a team")


def test_combination_rejects_finished_fixture(client):
    finished = [
        f
        for f in client.get("/fixtures", params={"date": "2026-10-14"}).json()["fixtures"]
        if f["status"] == "finished"
    ]
    upcoming = _upcoming_with_prediction(client, 3)
    other = next(
        u
        for u in upcoming
        if not {u["home_team"]["id"], u["away_team"]["id"]}
        & {finished[0]["home_team"]["id"], finished[0]["away_team"]["id"]}
    )
    payload = {
        "selections": [
            {"fixture_id": finished[0]["id"], "outcome": "HOME"},
            {"fixture_id": other["id"], "outcome": "HOME"},
        ]
    }
    r = client.post("/combinations/analyze", json=payload)
    assert r.status_code == 422 and "upcoming" in r.json()["detail"]


def test_openapi_schema_is_served(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in [
        "/health",
        "/fixtures",
        "/fixtures/{fixture_id}",
        "/fixtures/{fixture_id}/prediction",
        "/combinations/analyze",
    ]:
        assert p in paths


def test_highlights_are_upcoming_distinct_and_sorted(client, now):
    body = client.get("/highlights", params={"days": 7, "limit": 5}).json()
    items = body["items"]
    assert body["note"].startswith("추천이 아닙니다")
    assert 0 < len(items) <= 5
    edges = [h["edge"] for h in items]
    assert edges == sorted(edges, reverse=True)
    assert all(e >= body["min_edge"] for e in edges)
    assert len({h["fixture"]["id"] for h in items}) == len(items)
    for h in items:
        assert h["fixture"]["status"] == "scheduled"
        assert h["fixture"]["kickoff_at"] > now.isoformat().replace("+00:00", "Z")
        assert h["edge"] == pytest.approx(h["model_probability"] - h["fair_probability"])
        allowed = {"promoted_home", "promoted_away", "large_gap", "unverified_league"}
        assert set(h["caveats"]) <= allowed
        assert ("large_gap" in h["caveats"]) == (h["edge"] >= 0.10)
        verified = h["fixture"]["league"]["verified"]
        assert ("unverified_league" in h["caveats"]) == (not verified)


def test_highlights_respect_min_edge_and_validation(client):
    none = client.get("/highlights", params={"min_edge": 0.5}).json()
    assert none["items"] == []
    assert client.get("/highlights", params={"limit": 0}).status_code == 422
    assert client.get("/highlights", params={"days": 30}).status_code == 422


def test_prediction_includes_quality_report(client):
    fid = _upcoming_with_prediction(client, 1)[0]["id"]
    body = client.get(f"/fixtures/{fid}/prediction").json()
    q = body["quality"]
    names = {c["name"] for c in q["checks"]}
    assert {"upcoming", "ingestion_recent", "current_model", "odds_fresh", "team_history"} <= names
    assert q["ok"] == all(c["passed"] for c in q["checks"])


def test_today_pick_endpoint(client):
    body = client.get("/picks/today").json()
    assert body["tz"] == "Asia/Seoul" and body["is_demo"] is True
    assert body["status"] in {"published", "no_qualifying_match", "no_matches"}
    if body["status"] == "published":
        assert body["fixture"] and body["outcome"] in ("HOME", "DRAW", "AWAY")
        assert sum(body["probabilities"].values()) == pytest.approx(1.0)
        assert body["model"]["version"] and body["input_data_as_of"]
    again = client.get("/picks/today").json()
    assert again["pick_id"] == body["pick_id"]  # stable across refreshes
    assert client.get("/picks/today", params={"tz": "UTC"}).status_code == 422


def test_pick_history_and_status_endpoints(client):
    client.get("/picks/today")
    hist = client.get("/picks/history").json()
    assert hist["is_demo"] is True and len(hist["items"]) == 1
    assert hist["summary"]["settled"] == 0
    status = client.get("/status/data").json()
    assert status["provider"] == "mock" and status["last_success_at"]


def test_performance_endpoint_serves_imported_backtest(client, session_factory):
    from edge_api.services.evaluations import import_report

    with session_factory() as s:
        import_report(s)
        s.commit()
    body = client.get("/performance").json()
    ev = body["evaluation"]
    assert ev["n_matches"] >= 3000 and ev["has_odds"] is False
    names = {m["name"] for m in ev["test"]}
    assert {"base_rate", "production"} <= names
    assert ev["calibration"] and ev["daily_picks"]
    assert body["live"]["is_demo"] is True


def test_leagues_are_grouped_by_region_and_country(client):
    body = client.get("/leagues", params={"days": 7}).json()
    assert body["data_provider"] == "mock" and body["total_leagues"] == 4
    regions = {r["region"]: r for r in body["regions"]}
    assert list(regions) == ["europe", "asia"]  # catalogue order
    england = next(c for c in regions["europe"]["countries"] if c["country"] == "England")
    assert england["country_ko"] == "잉글랜드"
    names = [lg["name"] for lg in england["leagues"]]
    assert names == ["Premier League", "FA Cup"]  # featured rank order
    leagues = {lg["name"]: lg for c in regions["europe"]["countries"] for lg in c["leagues"]}
    cup, epl = leagues["FA Cup"], leagues["Premier League"]
    assert cup["type"] == "cup" and cup["predicted"] is False and cup["predicted_count"] == 0
    assert epl["predicted"] is True and 0 < epl["predicted_count"] <= epl["upcoming_count"]
    assert epl["verified"] is False  # synthetic data is never "verified"
    assert [lg["name"] for lg in body["featured"]][:3] == [
        "Premier League",
        "La Liga",
        "K League 1",
    ]
    kl = regions["asia"]["countries"][0]
    assert kl["country_ko"] == "대한민국" and kl["leagues"][0]["current_season"] == "2026"


def test_league_detail_and_404(client):
    first = client.get("/leagues").json()["featured"][0]
    detail = client.get(f"/leagues/{first['id']}").json()
    assert detail["name"] == first["name"] and detail["region"] == "europe"
    assert client.get("/leagues/999999").status_code == 404


def test_fixture_filters_by_league_region_and_featured(client):
    week = {"days": 7, "tz": "Asia/Seoul"}
    everything = client.get("/fixtures", params=week).json()["fixtures"]
    by_league = {}
    for f in everything:
        by_league.setdefault(f["league"]["name"], []).append(f)
    assert {"Premier League", "La Liga", "K League 1"} <= set(by_league)
    epl_id = by_league["Premier League"][0]["league"]["id"]
    only = client.get("/fixtures", params={**week, "league_id": epl_id}).json()["fixtures"]
    assert len(only) == len(by_league["Premier League"])
    asia = client.get("/fixtures", params={**week, "region": "asia"}).json()["fixtures"]
    assert asia and {f["league"]["name"] for f in asia} == {"K League 1"}
    spain = client.get("/fixtures", params={**week, "country": "Spain"}).json()["fixtures"]
    assert {f["league"]["name"] for f in spain} == {"La Liga"}
    featured = client.get("/fixtures", params={**week, "featured": True}).json()["fixtures"]
    assert len(featured) == len(everything)  # every mock league is featured
    cup = [f for f in everything if f["league"]["type"] == "cup"]
    assert all(f["model_probabilities"] is None for f in cup)  # cups are never predicted


def test_today_pick_reports_league_scope(client):
    body = client.get("/picks/today").json()
    assert body["league_scope"] == "verified"
    if body["status"] != "scheduled":
        assert body["matches_in_scope"] == body["matches_today"]  # mock: demo-wide scope


def test_fixture_detail_shows_team_news(client, session_factory, now):
    from datetime import timedelta

    from sqlalchemy import select

    from edge_api.config import Settings
    from edge_api.db.models import Fixture
    from edge_ingestion.providers import MockProvider
    from edge_ingestion.team_news import ingest_team_news

    settings = Settings(team_news_leagues="all", appearances_per_run=10_000)
    with session_factory() as s:
        ingest_team_news(s, MockProvider(now), now=now, settings=settings)  # minutes, absences
        f = s.scalars(
            select(Fixture)
            .where(Fixture.status == "scheduled", Fixture.kickoff_at > now)
            .order_by(Fixture.kickoff_at)
        ).first()
        before = f.kickoff_at - timedelta(minutes=30)
        ingest_team_news(s, MockProvider(before), now=before, settings=settings, lineups_only=True)
        s.commit()
        fid = f.id

    detail = client.get(f"/fixtures/{fid}").json()
    news = detail["team_news"]
    assert detail["lineups_announced"] is True and news["lineups_announced"] is True
    assert news["used_by_model"] is False and "반영하지 않았어요" in news["note"]
    for side in (news["home"], news["away"]):
        assert len(side["starters"]) == 11 and side["formation"]
        assert side["regulars_known"] is True and side["recent_matches"] >= 3
        regulars_in_xi = sum(p["regular"] for p in side["starters"])
        assert regulars_in_xi + len(side["missing_regulars"]) == 11
    listed = client.get("/fixtures", params={"days": 7}).json()["fixtures"]
    assert next(x for x in listed if x["id"] == fid)["lineups_announced"] is True


def test_team_news_is_absent_without_data(client):
    fid = _upcoming_with_prediction(client, 1)[0]["id"]
    assert client.get(f"/fixtures/{fid}").json()["team_news"] is None


def test_simulation_endpoint(client):
    fid = _upcoming_with_prediction(client, 1)[0]["id"]
    body = client.get(f"/fixtures/{fid}/simulation", params={"runs": 20000}).json()
    assert body["runs"] == 20000 and body["seed"] == body["prediction_id"]
    se = body["standard_error"]
    for k in ("home", "draw", "away"):
        assert abs(body["outcome_share"][k] - body["model_probabilities"][k]) < 5 * se + 0.005
    assert sum(share for _, share in body["total_goals"]) == pytest.approx(1.0)
    assert body["top_scores"] and body["note"].startswith("시뮬레이션은")
    replay = body["replay"]
    assert len(replay["goals"]) == replay["home_goals"] + replay["away_goals"]
    again = client.get(f"/fixtures/{fid}/simulation", params={"runs": 20000}).json()
    assert again == body  # same seed -> same result
    other = client.get(f"/fixtures/{fid}/simulation", params={"seed": 12345}).json()
    assert other["seed"] == 12345 and other["outcome_share"] != body["outcome_share"]


def test_simulation_validation_and_404(client):
    fid = _upcoming_with_prediction(client, 1)[0]["id"]
    assert client.get(f"/fixtures/{fid}/simulation", params={"runs": 10}).status_code == 422
    assert client.get("/fixtures/999999/simulation").status_code == 404
