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
KLEAGUE, FA_CUP, NO_ODDS_LEAGUE = 292, 45, 1000
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


KTEAMS = {
    2000 + k: (name, None)
    for k, name in enumerate(
        [
            "Ulsan HD",
            "Jeonbuk Motors",
            "Pohang Steelers",
            "FC Seoul",
            "Gwangju FC",
            "Gangwon FC",
            "Daejeon Citizen",
            "Gimcheon Sangmu",
            "Suwon FC",
            "Jeju SK",
            "FC Anyang",
            "Daegu FC",
        ],
        start=1,
    )
}
LOWLAND = {3000 + k: (f"Lowland {k}", None) for k in range(1, 7)}

# league id -> catalogue entry; "teams"/"start" per season start year
LEAGUES: dict[int, dict] = {
    LEAGUE: {
        "name": "Premier League",
        "type": "League",
        "country": ("England", "GB-ENG"),
        "odds": True,
        "teams": SEASON_TEAMS,
        "start": SEASON_START,
        "dates": ("2026-08-15", "2027-05-23"),
    },
    KLEAGUE: {
        "name": "K League 1",
        "type": "League",
        "country": ("South-Korea", "KR"),
        "odds": True,
        "teams": {2025: KTEAMS, 2026: KTEAMS},
        "start": {
            2025: datetime(2025, 3, 1, 5, tzinfo=UTC),
            2026: datetime(2026, 6, 1, 5, tzinfo=UTC),
        },
        "dates": ("2026-02-28", "2026-11-30"),
    },
    FA_CUP: {
        "name": "FA Cup",
        "type": "Cup",
        "country": ("England", "GB-ENG"),
        "odds": True,
        "teams": {2025: COMMON, 2026: COMMON},
        "start": {
            2025: datetime(2026, 1, 10, 15, tzinfo=UTC),
            2026: datetime(2026, 10, 3, 15, tzinfo=UTC),
        },
        "dates": ("2026-08-01", "2027-05-30"),
    },
    NO_ODDS_LEAGUE: {
        "name": "Lowland League",
        "type": "League",
        "country": ("Scotland", "GB-SCT"),
        "odds": False,
        "teams": {2025: LOWLAND, 2026: LOWLAND},
        "start": {
            2025: datetime(2025, 8, 9, 14, tzinfo=UTC),
            2026: datetime(2026, 8, 8, 14, tzinfo=UTC),
        },
        "dates": ("2026-08-08", "2027-04-30"),
    },
}


def leagues_payload() -> list[dict]:
    out = []
    for lid, lg in LEAGUES.items():
        country, code = lg["country"]
        start, end = lg["dates"]
        out.append(
            {
                "league": {
                    "id": lid,
                    "name": lg["name"],
                    "type": lg["type"],
                    "logo": f"l{lid}.png",
                },
                "country": {"name": country, "code": code, "flag": f"{code}.svg"},
                "seasons": [
                    {
                        "year": 2026,
                        "start": start,
                        "end": end,
                        "current": True,
                        "coverage": {"fixtures": {"events": True}, "odds": lg["odds"]},
                    }
                ],
            }
        )
    return out


def _status(fid: int, kickoff: datetime) -> str:
    if fid == POSTPONED_ID:
        return "PST"
    if fid == CANCELLED_ID:
        return "CANC"
    if fid == AWARDED_ID:
        return "AWD"
    if kickoff + timedelta(hours=2) <= REF:
        return "FT"
    if kickoff <= REF:
        return "2H"
    return "NS"


def _fixture_id(league: int, season: int, r: int, j: int) -> int:
    # Premier League ids keep the earlier format (e.g. 20260900)
    base = season * 10000 + r * 100 + j
    return base if league == LEAGUE else league * 10**8 + base


def fixture_items(season: int, league: int = LEAGUE) -> list[dict]:
    lg = LEAGUES[league]
    names = lg["teams"][season]
    ids = sorted(names)
    if lg["type"] == "Cup":  # a few one-off ties every two weeks
        rounds = [list(zip(ids[0::2], ids[1::2], strict=False))[k : k + 3] for k in (0, 3, 6)]
        rounds = [[(str(h), str(a)) for h, a in rnd] for rnd in rounds]
        spacing = 14
    else:
        rounds = _round_robin([str(i) for i in ids])
        spacing = 7
    items = []
    for r, pairs in enumerate(rounds):
        for j, (h, a) in enumerate(pairs):
            home, away = int(h), int(a)
            kickoff = lg["start"][season] + timedelta(days=spacing * r + (j % 2), hours=(j % 3) * 2)
            fid = _fixture_id(league, season, r, j)
            short = _status(fid, kickoff)
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
                        "id": league,
                        "name": lg["name"],
                        "country": lg["country"][0],
                        "season": season,
                        "round": f"Regular Season - {r + 1}",
                    },
                    "teams": {
                        "home": {"id": home, "name": names[home][0], "logo": f"t{home}.png"},
                        "away": {"id": away, "name": names[away][0], "logo": f"t{away}.png"},
                    },
                    "goals": {"home": hg, "away": ag},
                    "score": {
                        "halftime": {"home": None, "away": None},
                        "fulltime": {"home": hg, "away": ag},
                    },
                }
            )
    return items


def all_current_fixture_items() -> list[dict]:
    return [
        item
        for league, lg in LEAGUES.items()
        for season in lg["teams"]
        for item in fixture_items(season, league)
    ]


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
    for item in all_current_fixture_items():
        kickoff = datetime.fromisoformat(item["fixture"]["date"])
        if item["fixture"]["status"]["short"] != "NS" or kickoff > REF + timedelta(days=14):
            continue
        if not LEAGUES[item["league"]["id"]]["odds"]:
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
                "league": {"id": item["league"]["id"], "season": item["league"]["season"]},
                "fixture": {"id": fid, "timezone": "UTC", "date": item["fixture"]["date"]},
                "update": update,
                "bookmakers": bookmakers,
            }
        )
    return out


class FakeApiFootball:
    """Transport double: routes requests to synthetic payloads and records calls."""

    def __init__(
        self, *, odds_update: str = ODDS_UPDATE, page_size: int = 10, remaining: int = 7400
    ) -> None:
        self.remaining = remaining
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
        elif parsed.path == "/leagues":
            body = envelope("leagues", params, leagues_payload())
        elif parsed.path == "/teams":
            body = envelope("teams", params, teams_payload(int(params["season"])))
        elif parsed.path == "/fixtures":
            if "date" in params:
                items = [
                    i
                    for i in all_current_fixture_items()
                    if i["fixture"]["date"][:10] == params["date"]
                ]
            else:
                league, season = int(params["league"]), int(params["season"])
                known = season in LEAGUES.get(league, {}).get("teams", {})
                items = fixture_items(season, league) if known else []
            body = envelope("fixtures", params, items)
        elif parsed.path == "/odds":
            items = odds_items(self.odds_update)
            if "date" in params:
                items = [i for i in items if i["fixture"]["date"][:10] == params["date"]]
            if "league" in params:
                items = [i for i in items if str(i["league"]["id"]) == params["league"]]
            page = int(params.get("page", 1))
            total = max(1, -(-len(items) // self.page_size))
            chunk = items[(page - 1) * self.page_size : page * self.page_size]
            body = envelope("odds", params, chunk, page=page, total=total)
        else:
            return HttpResponse(404, {}, b"{}")
        headers = {
            "x-ratelimit-requests-remaining": str(self.remaining),
            "x-ratelimit-limit": "300",
        }
        return HttpResponse(200, headers, json.dumps(body).encode())


def json_response(body: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(body).encode())
