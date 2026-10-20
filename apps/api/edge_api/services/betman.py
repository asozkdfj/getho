"""Betman paper-betting research, stage A: which fixture a Betman event is, and
whether a stored Betman price could have been bought at a given moment.

Nothing here buys anything or recommends anything (docs/betman/README.md).

Mapping never links on names alone. An event is ``mapped`` automatically only
when a person has confirmed the league alias and both team aliases (scoped to
that league), and exactly one fixture of that league has those teams at home
and away within ``KICKOFF_TOLERANCE`` of the Betman kickoff. A reversed
home/away is ``rejected``; more than one candidate, or a fixture already
mapped to another event of the round, is ``ambiguous``; anything else is
``unmatched`` with suggestions a person can review (``manual_map``). A manual
decision is never overwritten by a later automatic run.
"""

from __future__ import annotations

import difflib
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from edge_api.betman_rules import unverified
from edge_api.db.models import (
    BetmanAlias,
    BetmanEventMapping,
    BetmanOddsSnapshot,
    Fixture,
)

KICKOFF_TOLERANCE = timedelta(hours=2)
SUGGESTIONS = 5
# rules any purchase of a priced selection depends on (tickets add their own in stage B)
PRICE_RULES = ("fixed_odds_at_purchase", "soccer_regular_time_1x2", "sale_close")


@dataclass(frozen=True)
class EventKey:
    product: str
    round_id: str
    event_number: int


@dataclass(frozen=True)
class EventInfo:
    """What Betman shows about an event (raw names, its kickoff)."""

    key: EventKey
    raw_league: str
    raw_home: str
    raw_away: str
    kickoff_at: datetime


def normalize(name: str) -> str:
    """Comparison form of a name: NFKC, case-folded, single spaces."""
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


# ------------------------------------------------------------------ aliases
def _latest(rows: Iterable[BetmanAlias]) -> dict[tuple[str, str, int | None], BetmanAlias]:
    out: dict[tuple[str, str, int | None], BetmanAlias] = {}
    for a in rows:  # ordered by created_at, id: later rows win
        scope = a.league_id if a.kind == "team" else None
        out[(a.kind, a.raw_name, scope)] = a
    return out


def aliases(session: Session) -> dict[tuple[str, str, int | None], BetmanAlias]:
    """Current aliases: (kind, normalized raw name, league scope for teams) -> row."""
    rows = session.scalars(
        select(BetmanAlias).order_by(BetmanAlias.created_at, BetmanAlias.id)
    ).all()
    return _latest(rows)


def learn_alias(
    session: Session, kind: str, raw_name: str, league_id: int, team_id: int | None = None
) -> bool:
    """Record a confirmed alias unless it is already the current one."""
    name = normalize(raw_name)
    current = aliases(session).get((kind, name, league_id if kind == "team" else None))
    if current is not None and (current.league_id, current.team_id) == (league_id, team_id):
        return False
    session.add(
        BetmanAlias(kind=kind, raw_name=name, league_id=league_id, team_id=team_id, method="manual")
    )
    session.flush()
    return True


# ------------------------------------------------------------------ mappings
def latest_mappings(
    session: Session, keys: Sequence[EventKey]
) -> dict[EventKey, BetmanEventMapping]:
    """The current mapping decision of each event (events without one are absent)."""
    rounds = {(k.product, k.round_id) for k in keys}
    if not rounds:
        return {}
    wanted = set(keys)
    out: dict[EventKey, BetmanEventMapping] = {}
    for m in session.scalars(
        select(BetmanEventMapping)
        .where(tuple_(BetmanEventMapping.product, BetmanEventMapping.round_id).in_(rounds))
        .order_by(BetmanEventMapping.created_at, BetmanEventMapping.id)
    ):
        key = EventKey(m.product, m.round_id, m.event_number)
        if key in wanted:
            out[key] = m
    return out


def _round_mappings(session: Session, product: str, round_id: str) -> dict[int, BetmanEventMapping]:
    """Current mapping of every event of a round, by event number."""
    current: dict[int, BetmanEventMapping] = {}
    for m in session.scalars(
        select(BetmanEventMapping)
        .where(BetmanEventMapping.product == product, BetmanEventMapping.round_id == round_id)
        .order_by(BetmanEventMapping.created_at, BetmanEventMapping.id)
    ):
        current[m.event_number] = m
    return current


def _fixture_row(f: Fixture, score: float | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "fixture_id": f.id,
        "league_id": f.league_id,
        "league": f"{f.league.country} - {f.league.name}",
        "home": f.home_team.name,
        "away": f.away_team.name,
        "kickoff_at": f.kickoff_at.isoformat(),
    }
    if score is not None:
        row["name_similarity"] = round(score, 3)
    return row


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def _suggestions(session: Session, provider: str, event: EventInfo) -> list[dict[str, Any]]:
    """Fixtures near the Betman kickoff, most similar names first (for a person to
    review; never linked automatically)."""
    near = session.scalars(
        select(Fixture).where(
            Fixture.provider == provider,
            Fixture.kickoff_at >= event.kickoff_at - KICKOFF_TOLERANCE,
            Fixture.kickoff_at <= event.kickoff_at + KICKOFF_TOLERANCE,
        )
    ).all()
    scored = [
        (
            (
                _similarity(event.raw_home, f.home_team.name)
                + _similarity(event.raw_away, f.away_team.name)
            )
            / 2,
            f,
        )
        for f in near
    ]
    scored.sort(key=lambda sf: (-sf[0], sf[1].id))
    return [{**_fixture_row(f, s), "suggestion": True} for s, f in scored[:SUGGESTIONS]]


def _taken_by(session: Session, event: EventKey, fixture_id: int) -> int | None:
    """Another event of the same round whose current mapping is this fixture."""
    for number, m in _round_mappings(session, event.product, event.round_id).items():
        if number != event.event_number and m.status == "mapped" and m.fixture_id == fixture_id:
            return number
    return None


@dataclass(frozen=True)
class Decision:
    status: str
    fixture_id: int | None
    reason: str | None
    candidates: list[dict[str, Any]]


def decide(session: Session, provider: str, event: EventInfo) -> Decision:
    """The automatic mapping decision for an event (not stored)."""
    known = aliases(session)
    league = known.get(("league", normalize(event.raw_league), None))
    if league is None:
        return Decision(
            "unmatched", None, "unknown_league_alias", _suggestions(session, provider, event)
        )
    home = known.get(("team", normalize(event.raw_home), league.league_id))
    away = known.get(("team", normalize(event.raw_away), league.league_id))
    if home is None or away is None:
        reason = "unknown_team_alias"
        return Decision("unmatched", None, reason, _suggestions(session, provider, event))
    window = (
        Fixture.provider == provider,
        Fixture.league_id == league.league_id,
        Fixture.kickoff_at >= event.kickoff_at - KICKOFF_TOLERANCE,
        Fixture.kickoff_at <= event.kickoff_at + KICKOFF_TOLERANCE,
    )
    direct = session.scalars(
        select(Fixture).where(
            *window, Fixture.home_team_id == home.team_id, Fixture.away_team_id == away.team_id
        )
    ).all()
    if len(direct) > 1:
        return Decision("ambiguous", None, "several_fixtures", [_fixture_row(f) for f in direct])
    if len(direct) == 1:
        f = direct[0]
        other = _taken_by(session, event.key, f.id)
        if other is not None:
            return Decision(
                "ambiguous", None, f"fixture_mapped_to_event_{other}", [_fixture_row(f)]
            )
        return Decision("mapped", f.id, None, [_fixture_row(f)])
    swapped = session.scalars(
        select(Fixture).where(
            *window, Fixture.home_team_id == away.team_id, Fixture.away_team_id == home.team_id
        )
    ).all()
    if swapped:
        return Decision("rejected", None, "home_away_reversed", [_fixture_row(f) for f in swapped])
    return Decision(
        "unmatched", None, "no_fixture_in_window", _suggestions(session, provider, event)
    )


def _record(session: Session, key: EventKey, d: Decision, method: str) -> BetmanEventMapping:
    m = BetmanEventMapping(
        product=key.product,
        round_id=key.round_id,
        event_number=key.event_number,
        fixture_id=d.fixture_id,
        status=d.status,
        method=method,
        reason=d.reason,
        candidates=d.candidates,
    )
    session.add(m)
    session.flush()
    return m


def auto_map(session: Session, provider: str, events: Sequence[EventInfo]) -> dict[EventKey, str]:
    """Decide each event and store the decision when it changed. A manual
    decision stays: automatic runs never replace it. Returns the current status."""
    current = latest_mappings(session, [e.key for e in events])
    out: dict[EventKey, str] = {}
    for e in events:
        now = current.get(e.key)
        if now is not None and now.method == "manual":
            out[e.key] = now.status
            continue
        d = decide(session, provider, e)
        same = now is not None and (now.status, now.fixture_id, now.reason) == (
            d.status,
            d.fixture_id,
            d.reason,
        )
        if not same:
            now = _record(session, e.key, d, "auto")
        out[e.key] = now.status if now is not None else d.status
    return out


class MappingError(ValueError):
    pass


def manual_map(
    session: Session,
    provider: str,
    event: EventInfo,
    fixture_id: int,
    *,
    learn_aliases: bool = False,
) -> BetmanEventMapping:
    """A person links an event to a fixture. Refused when the fixture's kickoff is
    outside the tolerance or the fixture is already mapped to another event of
    the round. With ``learn_aliases`` the Betman names become aliases so the next
    rounds map automatically."""
    f = session.get(Fixture, fixture_id)
    if f is None or f.provider != provider:
        raise MappingError(f"fixture {fixture_id} not found for provider {provider}")
    if abs(f.kickoff_at - event.kickoff_at) > KICKOFF_TOLERANCE:
        raise MappingError(
            f"kickoff differs by more than {KICKOFF_TOLERANCE}: "
            f"Betman {event.kickoff_at.isoformat()}, fixture {f.kickoff_at.isoformat()}"
        )
    other = _taken_by(session, event.key, f.id)
    if other is not None:
        raise MappingError(f"fixture {fixture_id} is already mapped to event {other}")
    if learn_aliases:
        learn_alias(session, "league", event.raw_league, f.league_id)
        learn_alias(session, "team", event.raw_home, f.league_id, f.home_team_id)
        learn_alias(session, "team", event.raw_away, f.league_id, f.away_team_id)
    return _record(session, event.key, Decision("mapped", f.id, None, [_fixture_row(f)]), "manual")


def manual_reject(session: Session, key: EventKey, reason: str) -> BetmanEventMapping:
    """A person says the event has no fixture here (or the current link is wrong)."""
    return _record(session, key, Decision("rejected", None, reason[:64], []), "manual")


# ------------------------------------------------------------------ prices
def latest_prices(
    session: Session, at: datetime, *, product: str | None = None, round_id: str | None = None
) -> dict[tuple[EventKey, str], BetmanOddsSnapshot]:
    """The newest price per event and selection stored by ``at``."""
    stmt = (
        select(BetmanOddsSnapshot)
        .where(BetmanOddsSnapshot.created_at <= at)
        .order_by(BetmanOddsSnapshot.created_at, BetmanOddsSnapshot.id)
    )
    if product is not None:
        stmt = stmt.where(BetmanOddsSnapshot.product == product)
    if round_id is not None:
        stmt = stmt.where(BetmanOddsSnapshot.round_id == round_id)
    out: dict[tuple[EventKey, str], BetmanOddsSnapshot] = {}
    for s in session.scalars(stmt):
        out[(EventKey(s.product, s.round_id, s.event_number), s.selection)] = s
    return out


def purchase_blockers(
    snapshot: BetmanOddsSnapshot, mapping: BetmanEventMapping | None, at: datetime
) -> list[str]:
    """Why this price could not have been bought at ``at`` (empty: it could).

    Only a price seen on Betman (not a historical proxy), stored and observed by
    ``at``, of a verified mapped event, on sale, before the sale closed and
    before kickoff, counts. Rule gaps are reported by ``rule_warnings``.
    """
    reasons = []
    if mapping is None or mapping.status != "mapped":
        reasons.append("not_mapped")
    if snapshot.price_evidence != "observed" or snapshot.source_observed_at is None:
        reasons.append("historical_proxy")
    elif snapshot.source_observed_at > at:
        reasons.append("observed_after_decision")
    if snapshot.created_at > at:
        reasons.append("stored_after_decision")
    if snapshot.sale_status != "on_sale":
        reasons.append(f"sale_{snapshot.sale_status}")
    if snapshot.sale_close_at is None:
        reasons.append("sale_close_unknown")
    elif at >= snapshot.sale_close_at:
        reasons.append("after_sale_close")
    if at >= snapshot.kickoff_at:
        reasons.append("after_kickoff")
    return reasons


def rule_warnings() -> list[str]:
    """``rules_unverified`` plus the rules a priced selection depends on that are
    not confirmed (empty when all are confirmed)."""
    gaps = unverified(list(PRICE_RULES))
    return ["rules_unverified", *gaps] if gaps else []


def event_info(session: Session, key: EventKey) -> EventInfo | None:
    """What the newest stored price of an event says about it."""
    s = session.scalars(
        select(BetmanOddsSnapshot)
        .where(
            BetmanOddsSnapshot.product == key.product,
            BetmanOddsSnapshot.round_id == key.round_id,
            BetmanOddsSnapshot.event_number == key.event_number,
        )
        .order_by(BetmanOddsSnapshot.created_at.desc(), BetmanOddsSnapshot.id.desc())
    ).first()
    if s is None:
        return None
    return EventInfo(key, s.raw_league, s.raw_home, s.raw_away, s.kickoff_at)


def status_report(
    session: Session, at: datetime, *, product: str | None = None, round_id: str | None = None
) -> dict[str, Any]:
    """Every event with prices stored by ``at``: raw names, current mapping, and
    per selection the price and why it could or could not have been bought."""
    prices = latest_prices(session, at, product=product, round_id=round_id)
    keys = sorted({k for k, _ in prices}, key=lambda k: (k.product, k.round_id, k.event_number))
    mappings = latest_mappings(session, keys)
    events = []
    counts = {"purchasable": 0, "blocked": 0}
    for key in keys:
        m = mappings.get(key)
        selections = {}
        first = None
        for sel in ("HOME", "DRAW", "AWAY"):
            s = prices.get((key, sel))
            if s is None:
                continue
            first = first or s
            blockers = purchase_blockers(s, m, at)
            counts["purchasable" if not blockers else "blocked"] += 1
            selections[sel] = {
                "odds": str(s.decimal_odds),
                "break_even_probability": round(1 / float(s.decimal_odds), 4),
                "observed_at": s.source_observed_at.isoformat() if s.source_observed_at else None,
                "stored_at": s.created_at.isoformat(),
                "price_evidence": s.price_evidence,
                "snapshot_id": s.id,
                "purchasable": not blockers,
                "blockers": blockers,
            }
        assert first is not None
        events.append(
            {
                "product": key.product,
                "round_id": key.round_id,
                "event_number": key.event_number,
                "league": first.raw_league,
                "home": first.raw_home,
                "away": first.raw_away,
                "kickoff_at": first.kickoff_at.isoformat(),
                "sale_close_at": first.sale_close_at.isoformat() if first.sale_close_at else None,
                "sale_status": first.sale_status,
                "single_allowed": first.single_allowed,
                "mapping": None
                if m is None
                else {
                    "status": m.status,
                    "method": m.method,
                    "fixture_id": m.fixture_id,
                    "reason": m.reason,
                    "candidates": m.candidates,
                    "decided_at": m.created_at.isoformat(),
                },
                "selections": selections,
            }
        )
    return {
        "at": at.isoformat(),
        "note": "paper-betting research input; nothing is bought or recommended",
        "rule_warnings": rule_warnings(),
        "selections": counts,
        "events": events,
    }
