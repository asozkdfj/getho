from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

PROBABILITY_TOLERANCE = 1e-9


class Outcome(StrEnum):
    """1X2 outcome. Values are part of the public API contract."""

    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"


@dataclass(frozen=True, slots=True)
class Probabilities1X2:
    home: float
    draw: float
    away: float

    def __post_init__(self) -> None:
        values = (self.home, self.draw, self.away)
        if any(not math.isfinite(v) or v < 0.0 or v > 1.0 for v in values):
            raise ValueError(f"probabilities must be finite and in [0, 1]: {values}")
        if abs(sum(values) - 1.0) > 1e-6:
            raise ValueError(f"probabilities must sum to 1, got {sum(values)!r}")

    @classmethod
    def normalized(cls, home: float, draw: float, away: float) -> Probabilities1X2:
        total = home + draw + away
        if total <= 0 or not math.isfinite(total):
            raise ValueError("cannot normalise non-positive probability mass")
        return cls(home / total, draw / total, away / total)

    def get(self, outcome: Outcome) -> float:
        return {Outcome.HOME: self.home, Outcome.DRAW: self.draw, Outcome.AWAY: self.away}[outcome]

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.home, self.draw, self.away)


@dataclass(frozen=True, slots=True)
class MatchResult:
    """A finished match used for fitting ratings. Team keys are opaque strings/ids.

    ``season`` (e.g. "2026-27") is optional; when present for every match the
    model can detect newly promoted teams and give them a realistic prior.
    """

    home: str
    away: str
    home_goals: int
    away_goals: int
    kickoff_at: datetime
    season: str | None = None

    def __post_init__(self) -> None:
        if self.home == self.away:
            raise ValueError("home and away team must differ")
        if self.home_goals < 0 or self.away_goals < 0:
            raise ValueError("goals must be non-negative")
        if self.kickoff_at.tzinfo is None:
            raise ValueError("kickoff_at must be timezone-aware (UTC)")
