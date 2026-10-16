import logging
from collections import Counter
from datetime import datetime, timedelta

import pytest

from edge_api.config import Settings
from edge_ingestion.providers import ApiFootballProvider, get_provider
from edge_ingestion.providers.api_football import (
    STATUS_MAP,
    bookmaker_slug,
    parse_league_selection,
    season_label,
    season_start_year,
    short_code,
)
from edge_ingestion.providers.http import HttpResponse, JsonHttpClient, ProviderError
from edge_ingestion.testing import (
    AWARDED_ID,
    CANCELLED_ID,
    KLEAGUE,
    LEAGUE,
    POSTPONED_ID,
    REF,
    FakeApiFootball,
    envelope,
    json_response,
    odds_items,
)

KEY = "secret-key-123"
DAY = (REF.replace(hour=0), REF.replace(hour=0) + timedelta(days=1))
WEEK = (REF, REF + timedelta(days=7))


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
    assert season_label(2026) == "2026-27" and season_label(2026, calendar_year=True) == "2026"
    assert short_code("Brighton & Hove") == "BRI" and short_code("1. FC Köln") == "FCK"
    assert parse_league_selection("all") is None and parse_league_selection("") is None
    assert parse_league_selection(" 39, 140 ") == {"39", "140"}
    with pytest.raises(ValueError):
        parse_league_selection("premier")
    assert set(STATUS_MAP.values()) <= {"scheduled", "live", "finished", "postponed", "cancelled"}


def test_factory_requires_key_and_uses_settings():
    with pytest.raises(ValueError, match="API_FOOTBALL_KEY"):
        get_provider("api_football", settings=Settings(data_provider="api_football"))
    p = get_provider(
        "api_football",
        settings=Settings(api_football_key=KEY, api_football_leagues="39,292"),
        reference_time=REF,
    )
    assert isinstance(p, ApiFootballProvider)
    assert p.league_ids == {"39", "292"}


def test_auth_header_sent_and_key_never_in_repr():
    p, fake = make()
    p.status()
    path, _, headers = fake.calls[0]
    assert path == "/status" and headers["x-apisports-key"] == KEY
    assert KEY not in repr(p) and KEY not in repr(p._client)


def test_league_catalogue_parsing_and_selection():
    p, fake = make()
    leagues = {lg.provider_id: lg for lg in p.get_leagues()}
    assert fake.calls[0][:2] == ("/leagues", {"current": "true"})
    epl, kl, cup = leagues["39"], leagues["292"], leagues["45"]
    assert (epl.type, epl.season, epl.season_year, epl.has_odds) == (
        "league",
        "2026-27",
        2026,
        True,
    )
    assert kl.season == "2026" and kl.country == "South-Korea"  # calendar-year season
    assert cup.type == "cup" and leagues["1000"].has_odds is False
    assert epl.logo_url == "l39.png" and epl.flag_url == "GB-ENG.svg"
    only, _ = make(leagues="292")
    assert [lg.provider_id for lg in only.get_leagues()] == ["292"]


def test_fixtures_by_date_cover_all_leagues_in_one_request_per_day():
    p, fake = make()
    fixtures = p.get_fixtures(*WEEK)
    fixture_calls = [c[1] for c in fake.calls if c[0] == "/fixtures"]
    assert len(fixture_calls) == 8  # 7 days touching 8 UTC calendar dates
    assert all(c["timezone"] == "UTC" and "date" in c for c in fixture_calls)
    assert {f.league_provider_id for f in fixtures} == {"39", "292", "45"}
    for f in fixtures:
        assert WEEK[0] <= f.kickoff_at < WEEK[1]
        assert f.home_team.name and f.home_team.logo_url
    kl = next(f for f in fixtures if f.league_provider_id == "292")
    assert kl.season == "2026"


def test_history_parsing_and_status_mapping():
    p, fake = make()
    epl = next(lg for lg in p.get_leagues() if lg.provider_id == "39")
    fixtures = {f.provider_id: f for f in p.get_league_history(epl)}
    history_calls = [c[1] for c in fake.calls if c[0] == "/fixtures"]
    assert [(c["league"], c["season"]) for c in history_calls] == [("39", "2025"), ("39", "2026")]
    statuses = Counter(f.status for f in fixtures.values())
    assert statuses["finished"] > 380 and statuses["scheduled"] > 0
    assert fixtures[str(POSTPONED_ID)].status == "postponed"
    assert fixtures[str(CANCELLED_ID)].status == "cancelled"
    awarded = fixtures[str(AWARDED_ID)]
    assert awarded.status == "cancelled" and awarded.home_score is None  # never trains the model
    for f in fixtures.values():
        assert f.kickoff_at.utcoffset() == timedelta(0)
        assert (f.home_score is not None) == (f.status == "finished")
        assert f.round is not None and f.season in ("2025-26", "2026-27")
        assert f.league_provider_id == str(LEAGUE)


def test_unknown_status_and_malformed_items_are_skipped(caplog):
    league = {"id": LEAGUE, "season": 2026, "round": "Regular Season - 9"}
    item_ok = {
        "fixture": {"id": 1, "date": REF.replace(hour=14).isoformat(), "status": {"short": "NS"}},
        "league": league,
        "teams": {"home": {"id": 33, "name": "A"}, "away": {"id": 34, "name": "B"}},
        "goals": {"home": None, "away": None},
    }
    weird = {**item_ok, "fixture": {**item_ok["fixture"], "id": 2, "status": {"short": "XYZ"}}}
    broken = {"fixture": {"id": 3}, "league": league}
    other_league = {**item_ok, "league": {**league, "id": 777}}  # not in the catalogue
    fake = FakeApiFootball()
    body = envelope("fixtures", {}, [item_ok, weird, broken, other_league])
    fake.overrides["/fixtures"] = [json_response(body)]
    p, _ = make(fake)
    with caplog.at_level(logging.WARNING):
        fixtures = p.get_fixtures(*DAY)
    assert [f.provider_id for f in fixtures] == ["1"]
    assert fixtures[0].round == 9


def test_odds_by_date_pagination_filtering_and_parsing():
    p, fake = make()
    upcoming = {
        f.provider_id: f.kickoff_at
        for f in p.get_fixtures(REF, REF + timedelta(days=14))
        if f.status == "scheduled"
    }
    skipped = sorted(upcoming)[0]
    wanted = {k: v for k, v in upcoming.items() if k != skipped}  # one deliberately not asked
    fake.calls.clear()
    odds = p.get_odds(wanted)
    days = {c[1]["date"] for c in fake.calls}
    assert days == {v.date().isoformat() for v in wanted.values()}  # only days we need
    assert all(c[1]["bet"] == "1" and "bookmaker" not in c[1] for c in fake.calls)
    priced = {o.fixture_provider_id for o in odds}
    assert skipped not in priced and priced <= set(wanted)
    assert {o.bookmaker for o in odds} == {"bet365", "pinnacle"}  # incomplete 1xBet dropped
    for o in odds:
        assert o.captured_at.isoformat() == "2026-10-15T06:00:04+00:00"
        assert min(o.odds_home, o.odds_draw, o.odds_away) > 1
        assert o.raw["source"] == "api_football"


def test_odds_paging_stops_once_every_wanted_fixture_is_priced():
    p, fake = make(fake=FakeApiFootball(page_size=1))
    items = odds_items()
    day = items[0]["fixture"]["date"][:10]
    same_day = [i for i in items if i["fixture"]["date"][:10] == day]
    assert len(same_day) > 1  # several pages exist for that day
    first = same_day[0]["fixture"]
    p.get_leagues()
    fake.calls.clear()
    odds = p.get_odds({str(first["id"]): datetime.fromisoformat(first["date"])})
    assert odds and len(fake.calls) == 1  # found on page 1: remaining pages skipped


def test_short_league_list_fetches_odds_per_league():
    p, fake = make(leagues=str(KLEAGUE))
    upcoming = {
        f.provider_id: f.kickoff_at for f in p.get_fixtures(*WEEK) if f.status == "scheduled"
    }
    fake.calls.clear()
    odds = p.get_odds(upcoming)
    assert odds and all(c[1]["league"] == str(KLEAGUE) for c in fake.calls)


def test_rate_limit_headers_set_pace_and_budget():
    p, _ = make(fake=FakeApiFootball(remaining=250), min_interval_seconds=6.5)
    p.get_leagues()
    assert p._client.min_interval_seconds == pytest.approx(60 / 300 * 1.05)
    assert p.daily_remaining == 250 and not p.budget_ok()  # below the 300 reserve
    p2, _ = make(fake=FakeApiFootball(remaining=5000))
    p2.get_leagues()
    assert p2.budget_ok()


def test_bookmaker_filter_is_forwarded():
    p, fake = make(bookmaker_id=8)
    p.get_odds({"123": REF})
    assert fake.calls[-1][1]["bookmaker"] == "8"


def test_in_band_errors_raise_provider_error():
    fake = FakeApiFootball()
    err = envelope(
        "fixtures", {}, [], errors={"plan": "Free plans do not have access to this season"}
    )
    fake.overrides["/fixtures"] = [json_response(err)]
    p, _ = make(fake)
    with pytest.raises(ProviderError, match="Free plans do not have access"):
        p.get_fixtures(*DAY)


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


def test_walkover_is_cancelled_without_a_score():
    league = {"id": LEAGUE, "season": 2026, "round": "Regular Season - 9"}
    item = {
        "fixture": {"id": 5, "date": REF.replace(hour=14).isoformat(), "status": {"short": "WO"}},
        "league": league,
        "teams": {"home": {"id": 33, "name": "A"}, "away": {"id": 34, "name": "B"}},
        "goals": {"home": 3, "away": 0},  # administrative result, not a played match
    }
    fake = FakeApiFootball()
    fake.overrides["/fixtures"] = [json_response(envelope("fixtures", {}, [item]))]
    p, _ = make(fake)
    (f,) = p.get_fixtures(*DAY)
    assert f.status == "cancelled" and (f.home_score, f.away_score) == (None, None)


def test_fixtures_by_ids_are_batched_and_parsed():
    p, fake = make()
    window = (REF - timedelta(days=14), REF + timedelta(days=14))
    known = sorted(f.provider_id for f in p.get_fixtures(*window))[:25]
    assert len(known) == 25
    fake.calls.clear()
    found = p.get_fixtures_by_ids([*known, known[0], "999999999"])  # repeat + unknown id
    calls = [c[1]["ids"].split("-") for c in fake.calls if c[0] == "/fixtures"]
    assert [len(c) for c in calls] == [20, 6]  # 20 ids per request, duplicates dropped
    assert sorted(f.provider_id for f in found) == known  # unknown id simply not returned
    assert all(f.kickoff_at.utcoffset() == timedelta(0) for f in found)


def test_fixtures_by_ids_stop_when_the_budget_is_low():
    p, fake = make(FakeApiFootball(remaining=100))
    known = sorted(f.provider_id for f in p.get_fixtures(REF, REF + timedelta(days=7)))
    fake.calls.clear()
    assert p.get_fixtures_by_ids(known) == []
    assert fake.calls == []
