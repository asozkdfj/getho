import logging
from collections import Counter
from datetime import timedelta

import pytest

from edge_api.config import Settings
from edge_ingestion.providers import ApiFootballProvider, get_provider
from edge_ingestion.providers.api_football import (
    STATUS_MAP,
    bookmaker_slug,
    season_label,
    season_start_year,
)
from edge_ingestion.providers.http import HttpResponse, JsonHttpClient, ProviderError
from edge_ingestion.testing import (
    AWARDED_ID,
    CANCELLED_ID,
    POSTPONED_ID,
    REF,
    FakeApiFootball,
    envelope,
    json_response,
)

KEY = "secret-key-123"
WINDOW = (REF - timedelta(days=400), REF + timedelta(days=30))


def make(fake=None, **kw) -> tuple[ApiFootballProvider, FakeApiFootball]:
    fake = fake or FakeApiFootball()
    kw.setdefault("min_interval_seconds", 0)
    return ApiFootballProvider(
        KEY, reference_time=REF, transport=fake, sleep=lambda _: None, **kw
    ), fake


def test_helpers():
    assert bookmaker_slug("Bet365") == "bet365"
    assert bookmaker_slug("William Hill") == "williamhill"
    assert season_start_year(REF) == 2026
    assert season_start_year(REF.replace(month=3)) == 2025
    assert season_label(2026) == "2026-27"
    assert set(STATUS_MAP.values()) <= {"scheduled", "live", "finished", "postponed", "cancelled"}


def test_factory_requires_key_and_uses_settings():
    with pytest.raises(ValueError, match="API_FOOTBALL_KEY"):
        get_provider("api_football", settings=Settings(data_provider="api_football"))
    p = get_provider(
        "api_football",
        settings=Settings(api_football_key=KEY, api_football_season=2025),
        reference_time=REF,
    )
    assert isinstance(p, ApiFootballProvider)
    assert p.seasons == [2024, 2025]


def test_auth_header_sent_and_key_never_in_repr():
    p, fake = make()
    p.status()
    path, _, headers = fake.calls[0]
    assert path == "/status" and headers["x-apisports-key"] == KEY
    assert KEY not in repr(p) and KEY not in repr(p._client)


def test_teams_merge_current_and_previous_season():
    p, fake = make()
    teams = {t.provider_id: t for t in p.get_teams()}
    assert len(teams) == 21  # 19 common + relegated + promoted
    assert teams["990"].short_name == "REL"  # missing code -> first 3 letters
    assert [c[1]["season"] for c in fake.calls] == ["2025", "2026"]
    assert all(c[1]["league"] == "39" for c in fake.calls)


def test_fixture_parsing_and_status_mapping():
    p, fake = make()
    fixtures = {f.provider_id: f for f in p.get_fixtures(*WINDOW)}
    assert all(c[1]["timezone"] == "UTC" for c in fake.calls)
    statuses = Counter(f.status for f in fixtures.values())
    assert statuses["finished"] > 380 and statuses["scheduled"] > 0
    assert fixtures[str(POSTPONED_ID)].status == "postponed"
    assert fixtures[str(CANCELLED_ID)].status == "cancelled"
    awarded = fixtures[str(AWARDED_ID)]
    assert awarded.status == "cancelled" and awarded.home_score is None  # never trains the model
    for f in fixtures.values():
        assert f.kickoff_at.utcoffset() == timedelta(0)
        assert WINDOW[0] <= f.kickoff_at < WINDOW[1]
        assert (f.home_score is not None) == (f.status == "finished")
        assert f.round is not None and f.season in ("2025-26", "2026-27")


def test_unknown_status_and_malformed_items_are_skipped(caplog):
    item_ok = {
        "fixture": {"id": 1, "date": "2026-10-20T14:00:00+00:00", "status": {"short": "NS"}},
        "league": {"round": "Regular Season - 9"},
        "teams": {"home": {"id": 33}, "away": {"id": 34}},
        "goals": {"home": None, "away": None},
    }
    weird = {**item_ok, "fixture": {**item_ok["fixture"], "id": 2, "status": {"short": "XYZ"}}}
    broken = {"fixture": {"id": 3}}
    fake = FakeApiFootball()
    body = envelope("fixtures", {}, [item_ok, weird, broken])
    fake.overrides["/fixtures"] = [json_response(body), json_response(envelope("fixtures", {}, []))]
    p, _ = make(fake)
    with caplog.at_level(logging.WARNING):
        fixtures = p.get_fixtures(*WINDOW)
    assert [f.provider_id for f in fixtures] == ["1"]
    assert fixtures[0].round == 9


def test_odds_pagination_filtering_and_parsing():
    p, fake = make()
    upcoming = [
        f.provider_id
        for f in p.get_fixtures(*WINDOW)
        if f.status == "scheduled" and f.kickoff_at <= REF + timedelta(days=14)
    ]
    fake.calls.clear()
    odds = p.get_odds(upcoming[:-1])  # one fixture deliberately not requested
    pages = [c[1]["page"] for c in fake.calls]
    assert pages == ["1", "2"]
    assert all(c[1]["bet"] == "1" and "bookmaker" not in c[1] for c in fake.calls)
    assert {o.fixture_provider_id for o in odds} == set(upcoming[:-1])
    assert {o.bookmaker for o in odds} == {"bet365", "pinnacle"}  # incomplete 1xBet market dropped
    for o in odds:
        assert o.captured_at.isoformat() == "2026-10-15T06:00:04+00:00"
        assert min(o.odds_home, o.odds_draw, o.odds_away) > 1
        assert o.raw["source"] == "api_football"


def test_bookmaker_filter_is_forwarded():
    p, fake = make(bookmaker_id=8)
    p.get_odds([])
    assert fake.calls[0][1]["bookmaker"] == "8"


def test_in_band_errors_raise_provider_error():
    fake = FakeApiFootball()
    err = envelope(
        "fixtures", {}, [], errors={"plan": "Free plans do not have access to this season"}
    )
    fake.overrides["/fixtures"] = [json_response(err)]
    p, _ = make(fake)
    with pytest.raises(ProviderError, match="Free plans do not have access"):
        p.get_fixtures(*WINDOW)


def test_retries_transient_failures_then_succeeds():
    sleeps = []
    fake = FakeApiFootball()
    fake.overrides["/status"] = [HttpResponse(503, {}, b""), HttpResponse(429, {}, b"")]
    p = ApiFootballProvider(
        KEY, reference_time=REF, transport=fake, min_interval_seconds=0, sleep=sleeps.append
    )
    assert p.status()["requests"]["limit_day"] == 100
    assert len(fake.calls) == 3 and sleeps == [1.0, 2.0]  # exponential backoff


def test_gives_up_after_max_attempts_and_does_not_retry_auth_errors():
    fake = FakeApiFootball()
    fake.overrides["/status"] = [HttpResponse(500, {}, b"")] * 3
    p, _ = make(fake)
    with pytest.raises(ProviderError, match="after 3 attempts"):
        p.status()
    fake2 = FakeApiFootball()
    fake2.overrides["/status"] = [HttpResponse(403, {}, b"{}")]
    p2, _ = make(fake2)
    with pytest.raises(ProviderError, match="HTTP 403"):
        p2.status()
    assert len(fake2.calls) == 1


def test_network_errors_are_retried():
    calls = []

    def flaky(url, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("read timed out")
        return json_response(envelope("status", {}, {"requests": {}}))

    client = JsonHttpClient("https://example.test", {}, transport=flaky, sleep=lambda _: None)
    assert client.get("/status")[0]["response"] == {"requests": {}}
    assert len(calls) == 2


def test_requests_are_spaced_for_rate_limits():
    now = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    client = JsonHttpClient(
        "https://example.test",
        {},
        transport=lambda *a: json_response({"response": []}),
        min_interval_seconds=6.5,
        sleep=sleep,
        clock=lambda: now[0],
    )
    client.get("/a")
    now[0] += 1.5
    client.get("/b")
    assert sleeps == [pytest.approx(5.0)]


def test_https_is_required():
    with pytest.raises(ValueError):
        JsonHttpClient("http://insecure.test", {})
