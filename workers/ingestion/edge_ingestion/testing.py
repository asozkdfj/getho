"""Test double: synthetic API-Football v3 payloads + fake transport (offline tests).

The *shape* follows the v3 response envelope
({get, parameters, errors, results, paging, response}); the *values* are made up.
Verify the shape against a live response with `edge check-provider` once a key
is available (see docs/providers/api-football.md).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from edge_ingestion.providers.http import HttpResponse
from edge_ingestion.providers.mock import _round_robin

REF = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
LEAGUE = 39
ODDS_UPDATE = "2026-10-15T06:00:04+00:00"

# team id -> (name, code); 990 is relegated after 2025, 991 promoted for 2026
COMMON = {
    33: ("Manchester United", "MUN"),
    34: ("Newcastle", "NEW"),
    35: ("Bournemouth", "BOU"),
    36: ("Fulham", "FUL"),
    39: ("Wolves", "WOL"),
    40: ("Liverpool", "LIV"),
    42: ("Arsenal", "ARS"),
    45: ("Everton", "EVE"),
    47: ("Tottenham", "TOT"),
    48: ("West Ham", "WES"),
    49: ("Chelsea", "CHE"),
    50: ("Manchester City", "MAC"),
    51: ("Brighton", "BRI"),
    52: ("Crystal Palace", "CRY"),
    55: ("Brentford", "BRE"),
    63: ("Leeds", "LEE"),
    65: ("Nottingham Forest", "NOT"),
    66: ("Aston Villa", "AST"),
    746: ("Sunderland", "SUN"),
}
SEASON_TEAMS = {
    2025: {**COMMON, 990: ("Relegated FC", None)},
    2026: {**COMMON, 991: ("Promoted Town", "PRO")},
}
SEASON_START = {
    2025: datetime(2025, 8, 16, 14, tzinfo=UTC),
    2026: datetime(2026, 8, 15, 14, tzinfo=UTC),
}

# special statuses in the current season (fixture ids)
POSTPONED_ID, CANCELLED_ID, AWARDED_ID = 2026_09_00, 2026_09_01, 2026_08_02


def envelope(endpoint: str, params: Mapping[str, object], response, page=1, total=1, errors=None):
    return {
        "get": endpoint,
        "parameters": {k: str(v) for k, v in params.items()},
        "errors": errors if errors is not None else [],
        "results": len(response) if isinstance(response, list) else 1,
        "paging": {"current": page, "total": total},
        "response": response,
    }


def teams_payload(season: int) -> list[dict]:
    return [
        {
            "team": {
                "id": tid,
                "name": name,
                "code": code,
                "country": "England",
                "national": False,
            },
            "venue": {"id": tid * 10, "name": f"{name} Stadium", "city": "City"},
        }
        for tid, (name, code) in SEASON_TEAMS[season].items()
    ]


def fixture_items(season: int) -> list[dict]:
    items = []
    ids = sorted(SEASON_TEAMS[season])
    for r, pairs in enumerate(_round_robin([str(i) for i in ids])):
        for j, (h, a) in enumerate(pairs):
            home, away = int(h), int(a)
            kickoff = SEASON_START[season] + timedelta(days=7 * r + (j % 2), hours=(j % 3) * 2)
            fid = season * 10000 + r * 100 + j
            if fid == POSTPONED_ID:
                short = "PST"
            elif fid == CANCELLED_ID:
                short = "CANC"
            elif fid == AWARDED_ID:
                short = "AWD"
            elif kickoff + timedelta(hours=2) <= REF:
                short = "FT"
            elif kickoff <= REF:
                short = "2H"
            else:
                short = "NS"
            done = short in ("FT", "AWD")
            hg, ag = (
                ((home * 7 + away * 3 + r) % 4, (home * 5 + away + r) % 3) if done else (None, None)
            )
            items.append(
                {
                    "fixture": {
                        "id": fid,
                        "referee": None,
                        "timezone": "UTC",
                        "date": kickoff.isoformat(),
                        "timestamp": int(kickoff.timestamp()),
                        "status": {"long": "", "short": short, "elapsed": 90 if done else None},
                    },
                    "league": {
                        "id": LEAGUE,
                        "name": "Premier League",
                        "country": "England",
                        "season": season,
                        "round": f"Regular Season - {r + 1}",
                    },
                    "teams": {
                        "home": {"id": home, "name": SEASON_TEAMS[season][home][0], "winner": None},
                        "away": {"id": away, "name": SEASON_TEAMS[season][away][0], "winner": None},
                    },
                    "goals": {"home": hg, "away": ag},
                    "score": {
                        "halftime": {"home": None, "away": None},
                        "fulltime": {"home": hg, "away": ag},
                    },
                }
            )
    return items


def _bet(home: str, draw: str, away: str) -> dict:
    return {
        "id": 1,
        "name": "Match Winner",
        "values": [
            {"value": "Home", "odd": home},
            {"value": "Draw", "odd": draw},
            {"value": "Away", "odd": away},
        ],
    }


def odds_items(update: str = ODDS_UPDATE) -> list[dict]:
    """Pre-match odds for scheduled fixtures within 14 days (like the real feed)."""
    out = []
    for item in fixture_items(2026):
        kickoff = datetime.fromisoformat(item["fixture"]["date"])
        if item["fixture"]["status"]["short"] != "NS" or kickoff > REF + timedelta(days=14):
            continue
        fid = item["fixture"]["id"]
        h = 1.6 + (fid % 7) * 0.35
        bookmakers = [
            {"id": 8, "name": "Bet365", "bets": [_bet(f"{h:.2f}", "3.60", f"{8 / h:.2f}")]},
            {
                "id": 4,
                "name": "Pinnacle",
                "bets": [_bet(f"{h + 0.05:.2f}", "3.70", f"{8 / h + 0.1:.2f}")],
            },
        ]
        if fid % 10 == 3:  # a bookmaker with an incomplete market -> ignored
            bookmakers.append(
                {
                    "id": 11,
                    "name": "1xBet",
                    "bets": [
                        {
                            "id": 1,
                            "name": "Match Winner",
                            "values": [{"value": "Home", "odd": "2.00"}],
                        }
                    ],
                }
            )
        out.append(
            {
                "league": {"id": LEAGUE, "season": 2026},
                "fixture": {"id": fid, "timezone": "UTC", "date": item["fixture"]["date"]},
                "update": update,
                "bookmakers": bookmakers,
            }
        )
    return out


class FakeApiFootball:
    """Transport double: routes requests to synthetic payloads and records calls."""

    def __init__(self, *, odds_update: str = ODDS_UPDATE, page_size: int = 10) -> None:
        self.calls: list[tuple[str, dict[str, str], Mapping[str, str]]] = []
        self.odds_update = odds_update
        self.page_size = page_size
        self.overrides: dict[str, list[HttpResponse]] = {}

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        parsed = urlparse(url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.calls.append((parsed.path, params, headers))
        if self.overrides.get(parsed.path):
            return self.overrides[parsed.path].pop(0)
        if parsed.path == "/status":
            body = envelope(
                "status",
                params,
                {
                    "account": {"firstname": "x"},
                    "subscription": {
                        "plan": "Free",
                        "end": "2027-01-01T00:00:00+00:00",
                        "active": True,
                    },
                    "requests": {"current": 3, "limit_day": 100},
                },
            )
        elif parsed.path == "/teams":
            body = envelope("teams", params, teams_payload(int(params["season"])))
        elif parsed.path == "/fixtures":
            body = envelope("fixtures", params, fixture_items(int(params["season"])))
        elif parsed.path == "/odds":
            items = odds_items(self.odds_update)
            page = int(params.get("page", 1))
            total = max(1, -(-len(items) // self.page_size))
            chunk = items[(page - 1) * self.page_size : page * self.page_size]
            body = envelope("odds", params, chunk, page=page, total=total)
        else:
            return HttpResponse(404, {}, b"{}")
        return HttpResponse(
            200, {"x-ratelimit-requests-remaining": "97"}, json.dumps(body).encode()
        )


def json_response(body: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(body).encode())
