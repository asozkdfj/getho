"""API-Football (api-sports.io, v3) provider.

Endpoints used (all GET, header ``x-apisports-key``):
  /status                                  account / quota (used by `check-provider`)
  /teams?league=39&season=S                teams of a season
  /fixtures?league=39&season=S&timezone=UTC
  /odds?league=39&season=S&bet=1[&bookmaker=B]&page=N   pre-match 1X2, paginated

Operational facts that shape this module (from the provider's docs/guides):
- pre-match odds appear ~1-14 days before kickoff, refresh ~every 3 hours and are
  kept for only ~7 days -> we must snapshot them ourselves (append-only table).
- errors come back as HTTP 200 with a non-empty ``errors`` field.
- the free plan allows ~100 requests/day and ~10/minute.

One pipeline run costs roughly: 2x teams + 2x fixtures (current + previous
season) + ceil(fixtures with odds / 10) odds pages, i.e. ~6-8 requests.

Everything provider-specific stays in this file; the core only sees the DTOs.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from edge_ingestion.providers.base import FixtureData, FootballDataProvider, OddsData, TeamData
from edge_ingestion.providers.http import JsonHttpClient, ProviderError, Transport, urllib_transport

logger = logging.getLogger(__name__)

MATCH_WINNER_BET_ID = 1  # "Match Winner" = 1X2
MAX_ODDS_PAGES = 20  # safety stop; EPL needs 1-3 pages

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


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


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
        league_id: int = 39,
        season: int | None = None,
        seasons_back: int = 1,
        bookmaker_id: int | None = None,
        min_interval_seconds: float = 6.5,
        timeout_seconds: float = 15.0,
        transport: Transport = urllib_transport,
        **client_kwargs: Any,
    ) -> None:
        if not api_key:
            raise ValueError("API_FOOTBALL_KEY is required for the api_football provider")
        ref = reference_time or datetime.now(UTC)
        self.league_id = league_id
        self.season = season or season_start_year(ref)
        self.seasons = [self.season - k for k in range(seasons_back, -1, -1)]  # oldest first
        self.bookmaker_id = bookmaker_id
        self._client = JsonHttpClient(
            base_url,
            {"x-apisports-key": api_key, "Accept": "application/json"},
            transport=transport,
            timeout=timeout_seconds,
            min_interval_seconds=min_interval_seconds,
            **client_kwargs,
        )

    def __repr__(self) -> str:
        return f"ApiFootballProvider(league={self.league_id}, season={self.season})"

    @property
    def requests_made(self) -> int:
        return self._client.requests_made

    # ------------------------------------------------------------- transport
    def _get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        payload, headers = self._client.get(path, params)
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
        remaining = headers.get("x-ratelimit-requests-remaining")
        if remaining is not None:
            logger.info("api_football %s ok; daily requests remaining=%s", path, remaining)
        return payload

    def status(self) -> dict[str, Any]:
        """Account/subscription/quota info (does not include the key)."""
        response = self._get("/status", {})["response"]
        return response if isinstance(response, dict) else {}

    # ------------------------------------------------------------------ teams
    def get_teams(self) -> list[TeamData]:
        teams: dict[str, TeamData] = {}
        for season in self.seasons:  # include relegated teams of the previous season
            payload = self._get("/teams", {"league": self.league_id, "season": season})
            for item in payload["response"]:
                team = item.get("team") or {}
                if team.get("id") is None or not team.get("name"):
                    continue
                code = (team.get("code") or team["name"][:3]).upper()[:10]
                teams[str(team["id"])] = TeamData(str(team["id"]), team["name"], code)
        return list(teams.values())

    # --------------------------------------------------------------- fixtures
    def get_fixtures(self, date_from: datetime, date_to: datetime) -> list[FixtureData]:
        out: list[FixtureData] = []
        for season in self.seasons:
            payload = self._get(
                "/fixtures", {"league": self.league_id, "season": season, "timezone": "UTC"}
            )
            for item in payload["response"]:
                fixture = self._parse_fixture(item, season)
                if fixture and date_from <= fixture.kickoff_at < date_to:
                    out.append(fixture)
        return out

    def _parse_fixture(self, item: Mapping[str, Any], season: int) -> FixtureData | None:
        try:
            fx, teams, goals = item["fixture"], item["teams"], item.get("goals") or {}
            short = fx["status"]["short"]
            status = STATUS_MAP.get(short)
            if status is None:
                logger.warning("fixture %s: unknown status %r, skipped", fx.get("id"), short)
                return None
            finished = status == "finished"
            return FixtureData(
                provider_id=str(fx["id"]),
                season=season_label(season),
                round=_parse_round((item.get("league") or {}).get("round")),
                kickoff_at=_parse_dt(fx["date"]),
                home_team_provider_id=str(teams["home"]["id"]),
                away_team_provider_id=str(teams["away"]["id"]),
                status=status,
                home_score=goals.get("home") if finished else None,
                away_score=goals.get("away") if finished else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("malformed fixture payload skipped: %s", exc)
            return None

    # ------------------------------------------------------------------- odds
    def get_odds(self, fixture_provider_ids: Sequence[str]) -> list[OddsData]:
        wanted = set(fixture_provider_ids)
        out: list[OddsData] = []
        page, total = 1, 1
        while page <= total and page <= MAX_ODDS_PAGES:
            params = {
                "league": self.league_id,
                "season": self.season,
                "bet": MATCH_WINNER_BET_ID,
                "bookmaker": self.bookmaker_id,
                "page": page,
            }
            payload = self._get("/odds", params)
            total = int((payload.get("paging") or {}).get("total") or 1)
            for item in payload["response"]:
                out.extend(self._parse_odds(item, wanted))
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
