"""Load Betman Proto 1X2 prices from a CSV or JSON file (paper-betting research).

One row per event:

    product, round_id, event_number, league, country, home, away,
    kickoff_at, sale_close_at, sale_status, single_allowed,
    odds_home, odds_draw, odds_away, observed_at

Required: product, round_id, event_number, league, home, away, kickoff_at and
at least one of the three odds. Times need a UTC offset (``2026-10-24T21:00+09:00``)
unless ``assume_tz`` is given for times typed without one. ``observed_at`` is
when the price was seen on Betman; without it (and without ``observed_now``)
the price is stored as a historical proxy and never counts as purchasable.

The whole file is checked first; any invalid row rejects the file (nothing is
stored). Loading the same bytes again stores nothing. Nothing is bought.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from edge_api.betman_rules import RULES_VERSION
from edge_api.db.models import BetmanImport, BetmanOddsSnapshot
from edge_api.services.betman import EventInfo, EventKey, auto_map

REQUIRED = ("product", "round_id", "event_number", "league", "home", "away", "kickoff_at")
SELECTIONS = {"odds_home": "HOME", "odds_draw": "DRAW", "odds_away": "AWAY"}
SALE_STATUSES = {"on_sale", "suspended", "closed", "unknown"}
TRUE, FALSE = {"true", "yes", "y", "1"}, {"false", "no", "n", "0"}


class BetmanImportError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class EventRow:
    key: EventKey
    league: str
    country: str | None
    home: str
    away: str
    kickoff_at: datetime
    sale_close_at: datetime | None
    sale_status: str
    single_allowed: bool | None
    odds: dict[str, Decimal]  # selection -> decimal odds
    observed_at: datetime | None

    def info(self) -> EventInfo:
        return EventInfo(self.key, self.league, self.home, self.away, self.kickoff_at)


def _records(text: str, fmt: str) -> list[dict[str, Any]]:
    if fmt == "json":
        data = json.loads(text)
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise BetmanImportError(["JSON must be a list of objects"])
        return data
    return list(csv.DictReader(io.StringIO(text)))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _time(value: Any, assume_tz: ZoneInfo | None, field: str) -> datetime:
    raw = _text(value)
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field}: not an ISO-8601 time: {raw!r}") from None
    if t.tzinfo is None:
        if assume_tz is None:
            raise ValueError(f"{field}: no UTC offset in {raw!r} (or pass --assume-tz)")
        t = t.replace(tzinfo=assume_tz)
    return t.astimezone(ZoneInfo("UTC"))


def _odds(value: Any, field: str) -> Decimal | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{field}: not a number: {raw!r}") from None
    if not d.is_finite() or not math.isfinite(float(d)):
        raise ValueError(f"{field}: not finite: {raw!r}")
    if d <= 1:
        raise ValueError(f"{field}: decimal odds must be above 1: {raw!r}")
    if d.as_tuple().exponent < -2:  # type: ignore[operator]
        raise ValueError(f"{field}: more than two decimals: {raw!r}")
    return d


def _bool(value: Any, field: str) -> bool | None:
    raw = _text(value).casefold()
    if not raw:
        return None
    if raw in TRUE:
        return True
    if raw in FALSE:
        return False
    raise ValueError(f"{field}: expected true/false, got {raw!r}")


def parse(
    text: str,
    fmt: str,
    *,
    now: datetime,
    assume_tz: str | None = None,
    observed_now: bool = False,
) -> list[EventRow]:
    """Validate every row; raise ``BetmanImportError`` listing all problems."""
    tz = ZoneInfo(assume_tz) if assume_tz else None
    errors: list[str] = []
    rows: list[EventRow] = []
    seen: set[EventKey] = set()
    records = _records(text, fmt)
    if not records:
        raise BetmanImportError(["no rows"])
    for i, r in enumerate(records, start=1):
        try:
            missing = [f for f in REQUIRED if not _text(r.get(f))]
            if missing:
                raise ValueError(f"missing {', '.join(missing)}")
            try:
                number = int(_text(r["event_number"]))
            except ValueError:
                raise ValueError(f"event_number: not an integer: {r['event_number']!r}") from None
            key = EventKey(_text(r["product"]), _text(r["round_id"]), number)
            if key in seen:
                raise ValueError(f"event {number} of round {key.round_id} appears twice")
            kickoff = _time(r["kickoff_at"], tz, "kickoff_at")
            close = (
                _time(r["sale_close_at"], tz, "sale_close_at")
                if _text(r.get("sale_close_at"))
                else None
            )
            if close is not None and close > kickoff:
                raise ValueError("sale_close_at is after kickoff_at")
            status = _text(r.get("sale_status")) or "unknown"
            if status not in SALE_STATUSES:
                raise ValueError(f"sale_status: one of {sorted(SALE_STATUSES)}, got {status!r}")
            odds = {
                sel: d for f, sel in SELECTIONS.items() if (d := _odds(r.get(f), f)) is not None
            }
            if not odds:
                raise ValueError("no odds")
            observed = None
            if _text(r.get("observed_at")):
                if observed_now:
                    raise ValueError("observed_at given together with --observed-now")
                observed = _time(r["observed_at"], tz, "observed_at")
            elif observed_now:
                observed = now
            if observed is not None and observed > now:
                raise ValueError(f"observed_at is in the future: {observed.isoformat()}")
            if _text(r["home"]).casefold() == _text(r["away"]).casefold():
                raise ValueError("home and away are the same")
            rows.append(
                EventRow(
                    key=key,
                    league=_text(r["league"]),
                    country=_text(r.get("country")) or None,
                    home=_text(r["home"]),
                    away=_text(r["away"]),
                    kickoff_at=kickoff,
                    sale_close_at=close,
                    sale_status=status,
                    single_allowed=_bool(r.get("single_allowed"), "single_allowed"),
                    odds=odds,
                    observed_at=observed,
                )
            )
            seen.add(key)
        except ValueError as exc:
            errors.append(f"row {i}: {exc}")
    if errors:
        raise BetmanImportError(errors)
    return rows


@dataclass(frozen=True)
class ImportResult:
    import_id: int
    already_loaded: bool
    events: int
    snapshots: int
    proxy_snapshots: int
    mapping: dict[str, int]


def store(
    session: Session,
    provider: str,
    data: bytes,
    rows: list[EventRow],
    *,
    source_mode: str,
    filename: str | None,
) -> ImportResult:
    """Append the import, its prices and the automatic mapping of its events."""
    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalars(
        select(BetmanImport).where(BetmanImport.artifact_sha256 == digest)
    ).first()
    if existing is not None:
        return ImportResult(existing.id, True, 0, 0, 0, {})
    imp = BetmanImport(
        source_mode=source_mode,
        filename=filename,
        artifact_sha256=digest,
        rows=len(rows),
        rules_version=RULES_VERSION,
    )
    session.add(imp)
    session.flush()
    snapshots = proxies = 0
    for r in rows:
        for selection, odds in r.odds.items():
            session.add(
                BetmanOddsSnapshot(
                    import_id=imp.id,
                    product=r.key.product,
                    round_id=r.key.round_id,
                    event_number=r.key.event_number,
                    market_type="1X2",
                    selection=selection,
                    raw_league=r.league,
                    raw_country=r.country,
                    raw_home=r.home,
                    raw_away=r.away,
                    kickoff_at=r.kickoff_at,
                    sale_close_at=r.sale_close_at,
                    sale_status=r.sale_status,
                    single_allowed=r.single_allowed,
                    decimal_odds=odds,
                    source_observed_at=r.observed_at,
                    price_evidence="observed" if r.observed_at is not None else "historical_proxy",
                    rules_version=RULES_VERSION,
                )
            )
            snapshots += 1
            proxies += r.observed_at is None
    session.flush()
    statuses = auto_map(session, provider, [r.info() for r in rows])
    counts: dict[str, int] = {}
    for s in statuses.values():
        counts[s] = counts.get(s, 0) + 1
    return ImportResult(imp.id, False, len(rows), snapshots, proxies, counts)
