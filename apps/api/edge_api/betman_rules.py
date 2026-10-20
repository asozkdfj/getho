"""Betman Proto rules the paper-betting research depends on (docs/betman/RULES.md).

Every rule is either ``confirmed`` (with its source, when it was checked and by
whom) or ``unverified``. An unverified rule is never filled in with a guess:
whatever depends on it is reported as ``rules_unverified`` (spec
docs/qa/2026-10-20-betman-profit-simulator-development-spec.md, section 3).
Change a rule only with a new ``RULES_VERSION``.
"""

from __future__ import annotations

from dataclasses import dataclass

RULES_VERSION = "betman-rules-2026-10-20"
FAQ = "https://sportstoto.co.kr/faq.php"


@dataclass(frozen=True)
class Rule:
    key: str
    description: str
    status: str  # "confirmed" | "unverified"
    value: str | None = None
    source: str | None = None
    checked_at: str | None = None
    checked_by: str | None = None


RULES: tuple[Rule, ...] = (
    Rule(
        "fixed_odds_at_purchase",
        "Proto is a fixed-odds product; the payout uses the odds at the time of purchase",
        "confirmed",
        "payout = stake x odds shown when bought",
        FAQ,
        "2026-10-20",
        "Codex QA (spec v0.1)",
    ),
    Rule(
        "soccer_regular_time_1x2",
        "Soccer 1X2 is settled on regular time, with the draw as its own outcome",
        "confirmed",
        "HOME / DRAW / AWAY after regular time",
        FAQ,
        "2026-10-20",
        "Codex QA (spec v0.1)",
    ),
    Rule("single_allowed", "Which events may be bought as a single", "unverified"),
    Rule("combination_size", "Minimum and maximum number of events in a ticket", "unverified"),
    Rule(
        "same_event_restrictions",
        "Restrictions on combining markets of the same match in one ticket",
        "unverified",
    ),
    Rule(
        "sale_close",
        "When sale closes relative to kickoff; suspension and odds changes",
        "unverified",
    ),
    Rule("stake_limits", "Minimum stake, stake unit, purchase and payout limits", "unverified"),
    Rule(
        "combined_odds_rounding",
        "Truncation or rounding of combined odds and of the payout",
        "unverified",
    ),
    Rule("void_and_cancel", "Settlement of cancelled, abandoned or void events", "unverified"),
    Rule("tax", "Tax or deduction on winnings and its unit", "unverified"),
)

BY_KEY = {r.key: r for r in RULES}


def unverified(keys: tuple[str, ...] | list[str]) -> list[str]:
    """The rules among ``keys`` that are not confirmed (unknown keys count as unverified)."""
    return [k for k in keys if k not in BY_KEY or BY_KEY[k].status != "confirmed"]
