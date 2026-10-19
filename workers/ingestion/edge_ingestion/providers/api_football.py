"""API-Football (api-sports.io, v3) provider - every league the plan covers.

Endpoints used (all GET, header ``x-apisports-key``):
  /status                                   account / quota (used by `check-provider`)
  /leagues?current=true                     catalogue: type, country, current season, coverage
  /fixtures?date=YYYY-MM-DD&timezone=UTC    every fixture of one day, all leagues, 1 request
  /fixtures?league=L&season=S&timezone=UTC  one league-season (history backfill)
  /odds?date=YYYY-MM-DD&bet=1&page=N        pre-match 1X2 of one day, all leagues, paginated
  /odds?league=L&season=S&bet=1&page=N      same, for a short explicit league list
  /injuries?date=YYYY-MM-DD                 injured / suspended / doubtful players of one day
  /fixtures?ids=a-b-c (<= 20 ids)           line-ups and player minutes of several fixtures

Operational facts that shape this module (from the provider's docs/guides):
- pre-match odds appear ~1-14 days before kickoff, refresh ~every 3 hours and are
  kept for only ~7 days -> we must snapshot them ourselves (append-only table).
- errors come back as HTTP 200 with a non-empty ``errors`` field.
- quotas differ per plan; responses carry the per-minute limit and the requests
  left today, which this client uses to pace itself and to stop optional work.

Request cost per run with all leagues: 1 (catalogue) + one per day of the
fixture window + odds pages for the next few days + 2 per league backfilled
(bounded per run). Fetching by date keeps the cost almost independent of the
number of leagues.

Everything provider-specific stays in this file; the core only sees the DTOs.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from edge_ingestion.providers.base import (
    AbsenceData,
    AbsenceReport,
    AppearanceData,
    FixtureData,
    FootballDataProvider,
    LeagueData,
    LineupData,
    OddsData,
    PlayerRef,
    TeamData,
)
from edge_ingestion.providers.http import JsonHttpClient, ProviderError, Transport, urllib_transport

logger = logging.getLogger(__name__)

MATCH_WINNER_BET_ID = 1  # "Match Winner" = 1X2
MAX_ODDS_PAGES = 100  # safety stop per day (or per league)
# With this many explicitly configured leagues or fewer, odds are fetched per
# league; otherwise per day for all leagues at once.
PER_LEAGUE_ODDS_MAX = 5
IDS_PER_REQUEST = 20  # /fixtures?ids= accepts up to 20 fixture ids
# /injuries player.type -> our status
ABSENCE_STATUS = {"missing fixture": "out", "questionable": "doubtful"}

# API-Football fixture.status.short -> our FixtureStatus values
STATUS_MAP: dict[str, str] = {
    "TBD": "scheduled",
    "NS": "scheduled",
    "1H": "live",
    "HT": "live",
    "2H": "live",
    "ET": "live",
    "BT": "live",
    "P": "live",
    "SUSP": "live",
    "INT": "live",
    "LIVE": "live",
    "FT": "finished",
    "AET": "finished",
    "PEN": "finished",
    "PST": "postponed",
    "CANC": "cancelled",
    "ABD": "cancelled",
    # Awarded / walkover: the score is administrative, so it must not train the model.
    "AWD": "cancelled",
    "WO": "cancelled",
}


def bookmaker_slug(name: str) -> str:
    """'Bet365' -> 'bet365', 'William Hill' -> 'williamhill'."""
    return re.sub(r"[^a-z0-9]", "", name.lower()) or "unknown"


def season_start_year(reference: datetime) -> int:
    """API-Football identifies a season by its start year (2026 for 2026-27)."""
    return reference.year if reference.month >= 7 else reference.year - 1


def season_label(start_year: int, calendar_year: bool = False) -> str:
    """'2026-27' for European-style seasons, '2026' for calendar-year leagues."""
    return str(start_year) if calendar_year else f"{start_year}-{(start_year + 1) % 100:02d}"


def short_code(name: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", name)
    return (letters[:3] or name[:3] or "???").upper()


def parse_league_selection(value: str | None) -> frozenset[str] | None:
    """'all' / '' -> None (every league); '39,140' -> {'39', '140'}."""
    if value is None or value.strip().lower() in ("", "all"):
        return None
    ids = frozenset(v.strip() for v in value.split(",") if v.strip())
    if not all(v.isdigit() for v in ids):
        raise ValueError(f"API_FOOTBALL_LEAGUES must be 'all' or comma-separated ids: {value!r}")
    return ids


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return dt.astimezone(UTC)


def _parse_round(value: str | None) -> int | None:
    match = re.search(r"(\d+)\s*$", value or "")
    return int(match.group(1)) if match else None


class ApiFootballProvider(FootballDataProvider):
    name = "api_football"

    def __init__(
        self,
        api_key: str,
        *,
        reference_time: datetime | None = None,
        base_url: str = "https://v3.football.api-sports.io",
        leagues: str | None = "all",
        bookmaker_id: int | None = None,
        min_interval_seconds: float = 6.5,
        timeout_seconds: float = 15.0,
        min_remaining_requests: int = 300,
        transport: Transport = urllib_transport,
        **client_kwargs: Any,
    ) -> None:
        if not api_key:
            raise ValueError("API_FOOTBALL_KEY is required for the api_football provider")
        self.reference_time = reference_time or datetime.now(UTC)
        self.league_ids = parse_league_selection(leagues)
        self.bookmaker_id = bookmaker_id
        self.min_remaining_requests = min_remaining_requests
        self.daily_remaining: int | None = None
        self._catalogue: dict[str, LeagueData] | None = None
        self._client = JsonHttpClient(
            base_url,
            {"x-apisports-key": api_key, "Accept": "application/json"},
            transport=transport,
            timeout=timeout_seconds,
            min_interval_seconds=min_interval_seconds,
            **client_kwargs,
        )

    def __repr__(self) -> str:
        scope = "all" if self.league_ids is None else ",".join(sorted(self.league_ids))
        return f"ApiFootballProvider(leagues={scope})"

    @property
    def requests_made(self) -> int:
        return self._client.requests_made

    def budget_ok(self) -> bool:
        return self.daily_remaining is None or self.daily_remaining > self.min_remaining_requests

    # ------------------------------------------------------------- transport
    def _get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        payload, headers = self._client.get(path, params)
        self._observe_rate_limits(headers)
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:  # API-Football reports errors in-band with HTTP 200
            detail = (
                "; ".join(f"{k}: {v}" for k, v in errors.items())
                if isinstance(errors, dict)
                else str(errors)
            )
            raise ProviderError(f"API-Football {path} error: {detail}")
        if not isinstance(payload, dict) or "response" not in payload:
            raise ProviderError(f"API-Football {path}: unexpected payload shape")
        return payload

    def _observe_rate_limits(self, headers: Mapping[str, str]) -> None:
        """Pace by the plan's per-minute limit and remember the daily allowance left."""
        per_minute = _int_header(headers, "x-ratelimit-limit")
        if per_minute:
            # 10/min (free) -> 6.3s, 300/min (pro) -> 0.21s; never faster than the plan allows
            self._client.min_interval_seconds = 60.0 / per_minute * 1.05
        remaining = _int_header(headers, "x-ratelimit-requests-remaining")
        if remaining is not None:
            self.daily_remaining = remaining

    def status(self) -> dict[str, Any]:
        """Account/subscription/quota info (does not include the key)."""
        response = self._get("/status", {})["response"]
        return response if isinstance(response, dict) else {}

    # ---------------------------------------------------------------- leagues
    def get_leagues(self) -> list[LeagueData]:
        payload = self._get("/leagues", {"current": "true"})
        catalogue: dict[str, LeagueData] = {}
        for item in payload["response"]:
            league = self._parse_league(item)
            if league and (self.league_ids is None or league.provider_id in self.league_ids):
                catalogue[league.provider_id] = league
        self._catalogue = catalogue
        return list(catalogue.values())

    def _leagues(self) -> dict[str, LeagueData]:
        if self._catalogue is None:
            self.get_leagues()
        return self._catalogue or {}

    @staticmethod
    def _parse_league(item: Mapping[str, Any]) -> LeagueData | None:
        try:
            lg, country = item["league"], item.get("country") or {}
            seasons = item.get("seasons") or []
            current = next((s for s in seasons if s.get("current")), seasons[-1] if seasons else {})
            year = current.get("year")
            start, end = current.get("start") or "", current.get("end") or ""
            calendar_year = bool(start[:4]) and start[:4] == end[:4]
            coverage = current.get("coverage") or {}
            odds = coverage.get("odds") is True
            return LeagueData(
                provider_id=str(lg["id"]),
                name=str(lg["name"]),
                country=str(country.get("name") or "World"),
                country_code=country.get("code"),
                type="cup" if str(lg.get("type", "")).lower() == "cup" else "league",
                season=season_label(int(year), calendar_year) if year else None,
                season_year=int(year) if year else None,
                has_odds=odds,
                has_injuries=coverage.get("injuries") is True,
                logo_url=lg.get("logo"),
                flag_url=country.get("flag"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("malformed league payload skipped: %s", exc)
            return None

    def _season_label(self, league_id: str, year: int) -> str:
        league = self._leagues().get(league_id)
        calendar_year = bool(league and league.season and "-" not in league.season)
        return season_label(year, calendar_year)

    # --------------------------------------------------------------- fixtures
    def get_fixtures(self, date_from: datetime, date_to: datetime) -> list[FixtureData]:
        out: list[FixtureData] = []
        served = self._leagues()
        for day in _days(date_from, date_to):
            payload = self._get("/fixtures", {"date": day.isoformat(), "timezone": "UTC"})
            for item in payload["response"]:
                league_id = str((item.get("league") or {}).get("id"))
                if league_id not in served:
                    continue
                fixture = self._parse_fixture(item)
                if fixture and date_from <= fixture.kickoff_at < date_to:
                    out.append(fixture)
        return out

    def get_league_history(self, league: LeagueData) -> list[FixtureData]:
        if league.season_year is None:
            return []
        out: list[FixtureData] = []
        for year in (league.season_year - 1, league.season_year):
            payload = self._get(
                "/fixtures",
                {"league": league.provider_id, "season": year, "timezone": "UTC"},
            )
            out.extend(f for f in map(self._parse_fixture, payload["response"]) if f)
        return out

    def _parse_fixture(self, item: Mapping[str, Any]) -> FixtureData | None:
        try:
            fx, teams, goals = item["fixture"], item["teams"], item.get("goals") or {}
            league = item["league"]
            short = fx["status"]["short"]
            status = STATUS_MAP.get(short)
            if status is None:
                logger.warning("fixture %s: unknown status %r, skipped", fx.get("id"), short)
                return None
            finished = status == "finished"
            league_id = str(league["id"])
            return FixtureData(
                provider_id=str(fx["id"]),
                league_provider_id=league_id,
                season=self._season_label(league_id, int(league["season"])),
                round=_parse_round(league.get("round")),
                kickoff_at=_parse_dt(fx["date"]),
                home_team=_team(teams["home"]),
                away_team=_team(teams["away"]),
                status=status,
                home_score=goals.get("home") if finished else None,
                away_score=goals.get("away") if finished else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("malformed fixture payload skipped: %s", exc)
            return None

    # ------------------------------------------------------------------- odds
    def get_odds(self, fixtures: Mapping[str, datetime]) -> list[OddsData]:
        if not fixtures:
            return []
        queries: list[tuple[dict[str, Any], set[str]]]
        if self.league_ids is not None and len(self.league_ids) <= PER_LEAGUE_ODDS_MAX:
            queries = [
                ({"league": lg.provider_id, "season": lg.season_year}, set(fixtures))
                for lg in self._leagues().values()
                if lg.has_odds and lg.season_year is not None
            ]
        else:
            by_day: dict[date, set[str]] = {}
            for pid, kickoff in fixtures.items():
                by_day.setdefault(kickoff.astimezone(UTC).date(), set()).add(pid)
            queries = [
                ({"date": d.isoformat(), "timezone": "UTC"}, ids)
                for d, ids in sorted(by_day.items())
            ]
        out: list[OddsData] = []
        for query, wanted in queries:
            if not self.budget_ok():
                logger.warning("api_football daily budget nearly used up; odds fetch stopped")
                break
            out.extend(self._odds_pages(query, wanted))
        return out

    def _odds_pages(self, query: Mapping[str, Any], wanted: set[str]) -> list[OddsData]:
        out: list[OddsData] = []
        found: set[str] = set()
        page, total = 1, 1
        while page <= total and page <= MAX_ODDS_PAGES:
            params = {
                **query,
                "bet": MATCH_WINNER_BET_ID,
                "bookmaker": self.bookmaker_id,
                "page": page,
            }
            payload = self._get("/odds", params)
            total = int((payload.get("paging") or {}).get("total") or 1)
            for item in payload["response"]:
                parsed = self._parse_odds(item, wanted)
                out.extend(parsed)
                found.update(o.fixture_provider_id for o in parsed)
            if wanted <= found:  # every fixture we need is priced: skip the other pages
                break
            page += 1
        return out

    def _parse_odds(self, item: Mapping[str, Any], wanted: set[str]) -> list[OddsData]:
        try:
            fixture_id = str(item["fixture"]["id"])
            if fixture_id not in wanted:
                return []
            # `update` = when API-Football last refreshed these prices. Using it as
            # captured_at makes re-fetching unchanged prices a no-op (idempotent).
            captured_at = _parse_dt(item["update"])
            bookmakers = item.get("bookmakers") or []
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("malformed odds payload skipped: %s", exc)
            return []
        out = []
        for bm in bookmakers:
            prices = self._match_winner_prices(bm)
            if prices is None:
                continue
            out.append(
                OddsData(
                    fixture_provider_id=fixture_id,
                    bookmaker=bookmaker_slug(str(bm.get("name", ""))),
                    odds_home=prices["Home"],
                    odds_draw=prices["Draw"],
                    odds_away=prices["Away"],
                    captured_at=captured_at,
                    raw={
                        "source": "api_football",
                        "fixture_id": fixture_id,
                        "update": item["update"],
                        "bookmaker": {"id": bm.get("id"), "name": bm.get("name")},
                    },
                )
            )
        return out

    # -------------------------------------------------------------- team news
    def get_absences(self, fixtures: Mapping[str, datetime]) -> list[AbsenceData]:
        return self.get_absence_report(fixtures).absences

    def get_absence_report(self, fixtures: Mapping[str, datetime]) -> AbsenceReport:
        """One /injuries request per kickoff day. Only days actually fetched are
        covered: a day skipped for the request budget stays unknown. A fixture
        with a malformed row is not covered and none of its rows are kept (a
        partial or empty list must not replace its last good report); a row that
        cannot even be tied to a fixture leaves the whole day uncovered."""
        by_day: dict[date, set[str]] = {}
        for pid, kickoff in fixtures.items():
            by_day.setdefault(kickoff.astimezone(UTC).date(), set()).add(pid)
        out: list[AbsenceData] = []
        covered: set[str] = set()
        for day, wanted in sorted(by_day.items()):
            if not self.budget_ok():
                break
            payload = self._get("/injuries", {"date": day.isoformat(), "timezone": "UTC"})
            parsed: list[AbsenceData] = []
            broken: set[str] = set()
            unattributable = False
            for item in payload["response"]:
                fixture_id = self._fixture_id_of(item)
                if fixture_id is None:
                    unattributable = True
                elif fixture_id in wanted:
                    absence = self._parse_absence(item, wanted)
                    if absence is None:
                        broken.add(fixture_id)
                    else:
                        parsed.append(absence)
            if unattributable:
                logger.warning("injuries of %s: a row without a fixture; day left unknown", day)
                continue
            if broken:
                logger.warning("injuries of %s: malformed rows for %d fixtures", day, len(broken))
            out += [a for a in parsed if a.fixture_provider_id not in broken]
            covered |= wanted - broken
        return AbsenceReport(out, frozenset(covered))

    @staticmethod
    def _fixture_id_of(item: Any) -> str | None:
        try:
            return str(item["fixture"]["id"])
        except (KeyError, TypeError):
            return None

    @staticmethod
    def _parse_absence(item: Mapping[str, Any], wanted: set[str]) -> AbsenceData | None:
        try:
            fixture_id = str(item["fixture"]["id"])
            if fixture_id not in wanted:
                return None
            player = item["player"]
            status = ABSENCE_STATUS.get(str(player.get("type", "")).strip().lower(), "doubtful")
            return AbsenceData(
                fixture_provider_id=fixture_id,
                team_provider_id=str(item["team"]["id"]),
                player=PlayerRef(str(player["id"]), str(player["name"])),
                status=status,
                reason=player.get("reason"),
            )
        except (KeyError, TypeError) as exc:
            logger.warning("malformed injury payload skipped: %s", exc)
            return None

    def _fixture_details(self, fixture_provider_ids: list[str]) -> list[Mapping[str, Any]]:
        out: list[Mapping[str, Any]] = []
        ids = list(dict.fromkeys(fixture_provider_ids))
        for i in range(0, len(ids), IDS_PER_REQUEST):
            if not self.budget_ok():
                logger.warning(
                    "api_football daily budget nearly used up; fixture details postponed"
                )
                break
            chunk = ids[i : i + IDS_PER_REQUEST]
            out.extend(self._get("/fixtures", {"ids": "-".join(chunk)})["response"])
        return out

    def get_fixtures_by_ids(self, fixture_provider_ids: list[str]) -> list[FixtureData]:
        """/fixtures?ids= (20 per request) returns full fixture objects."""
        return [
            f for f in map(self._parse_fixture, self._fixture_details(fixture_provider_ids)) if f
        ]

    def get_lineups(self, fixture_provider_ids: list[str]) -> list[LineupData]:
        out: list[LineupData] = []
        for item in self._fixture_details(fixture_provider_ids):
            try:
                fixture_id = str(item["fixture"]["id"])
                for team in item.get("lineups") or []:
                    starters = tuple(_player(p) for p in team.get("startXI") or [])
                    if len(starters) < 11:
                        continue  # not published yet (or incomplete)
                    out.append(
                        LineupData(
                            fixture_provider_id=fixture_id,
                            team_provider_id=str(team["team"]["id"]),
                            formation=team.get("formation"),
                            starters=starters,
                            substitutes=tuple(_player(p) for p in team.get("substitutes") or []),
                        )
                    )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("malformed lineup payload skipped: %s", exc)
        return out

    def get_appearances(self, fixture_provider_ids: list[str]) -> list[AppearanceData]:
        out: list[AppearanceData] = []
        for item in self._fixture_details(fixture_provider_ids):
            try:
                fixture_id = str(item["fixture"]["id"])
                for team in item.get("players") or []:
                    team_id = str(team["team"]["id"])
                    for entry in team.get("players") or []:
                        games = ((entry.get("statistics") or [{}])[0] or {}).get("games") or {}
                        minutes = games.get("minutes")
                        if not minutes:
                            continue  # unused substitute
                        out.append(
                            AppearanceData(
                                fixture_provider_id=fixture_id,
                                team_provider_id=team_id,
                                player=PlayerRef(
                                    str(entry["player"]["id"]),
                                    str(entry["player"]["name"]),
                                    games.get("number"),
                                    games.get("position"),
                                ),
                                started=not games.get("substitute", False),
                                minutes=max(0, min(int(minutes), 130)),
                            )
                        )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("malformed player stats payload skipped: %s", exc)
        return out

    @staticmethod
    def _match_winner_prices(bookmaker: Mapping[str, Any]) -> dict[str, float] | None:
        for bet in bookmaker.get("bets") or []:
            if bet.get("id") != MATCH_WINNER_BET_ID:
                continue
            prices: dict[str, float] = {}
            for v in bet.get("values") or []:
                try:
                    odd = float(v["odd"])
                except (KeyError, TypeError, ValueError):
                    continue
                if math.isfinite(odd):
                    prices[str(v.get("value"))] = odd
            if {"Home", "Draw", "Away"} <= prices.keys():
                return prices
        return None


def _player(item: Mapping[str, Any]) -> PlayerRef:
    p = item["player"]
    return PlayerRef(str(p["id"]), str(p["name"]), p.get("number"), p.get("pos"))


def _team(item: Mapping[str, Any]) -> TeamData:
    name = str(item["name"])
    return TeamData(str(item["id"]), name, short_code(name), item.get("logo"))


def _days(date_from: datetime, date_to: datetime) -> list[date]:
    """UTC calendar days touched by [date_from, date_to)."""
    first = date_from.astimezone(UTC).date()
    last = (date_to.astimezone(UTC) - timedelta(microseconds=1)).date()
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
