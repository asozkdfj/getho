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
