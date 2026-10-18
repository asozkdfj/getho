"""Match review: what the service said before a day's matches, and what happened.

For every fixture of a local calendar day: the newest prediction that existed
before kickoff (pre-kickoff data, stored before kickoff), the market's fair
probabilities from the odds that prediction used, and the result. The summary
compares the hits with the number the probabilities expected (their sum): over
a day both are small numbers, so a gap is usually luck, and the page says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import DailyPick, Fixture, FixtureStatus, Prediction
from edge_api.services import queries
from edge_api.services.analysis import market_view, model_probabilities
from edge_api.services.leagues import verified_league_ids
from edge_api.services.picks import effective_status
from edge_ml.core import Outcome, Probabilities1X2
from edge_ml.picks import best_outcome

# Same tiers as the match cards (apps/web/lib/confidence.ts).
TIERS = (("high", 0.65), ("medium", 0.55))


def actual_outcome(f: Fixture) -> Outcome | None:
    if f.status != FixtureStatus.FINISHED.value or f.home_score is None or f.away_score is None:
        return None
    if f.home_score > f.away_score:
        return Outcome.HOME
    return Outcome.DRAW if f.home_score == f.away_score else Outcome.AWAY


def tier_of(probability: float) -> str | None:
    return next((name for name, low in TIERS if probability >= low), None)


@dataclass(slots=True)
class ReviewItem:
    fixture: Fixture
    prediction: Prediction | None
    model: Probabilities1X2 | None
    market: Probabilities1X2 | None
    actual: Outcome | None

    @property
    def top(self) -> tuple[Outcome, float] | None:
        return best_outcome(self.model) if self.model else None

    @property
    def market_top(self) -> tuple[Outcome, float] | None:
        return best_outcome(self.market) if self.market else None

    @property
    def evaluated(self) -> bool:
        return self.model is not None and self.actual is not None

    @property
    def hit(self) -> bool | None:
        return self.top[0] == self.actual if self.evaluated and self.top else None

    @property
    def market_hit(self) -> bool | None:
        if not self.evaluated or self.market_top is None:
            return None
        return self.market_top[0] == self.actual


@dataclass(slots=True)
class ReviewDay:
    day: date
    tz: str
    start_utc: datetime
    end_utc: datetime
    items: list[ReviewItem]
    verified: frozenset[str]
    demo: bool
    pick: DailyPick | None
    summaries: dict[str, dict[str, Any]] = field(default_factory=dict)


def summarize(items: list[ReviewItem]) -> dict[str, Any]:
    done = [i for i in items if i.evaluated]
    tops = [i.top for i in done if i.top]
    hits = sum(1 for i in done if i.hit)
    market = [i for i in done if i.market_hit is not None]
    tiers = {}
    for name, _ in TIERS:
        sel = [i for i in done if i.top and tier_of(i.top[1]) == name]
        tiers[name] = {
            "matches": len(sel),
            "hits": sum(1 for i in sel if i.hit),
            "expected_hits": sum(i.top[1] for i in sel if i.top),
        }
    return {
        "matches": len(done),
        "hits": hits,
        "expected_hits": sum(p for _, p in tops),
        # spread of the hit count over these same matches (independent outcomes)
        "hit_variance": sum(p * (1 - p) for _, p in tops),
        "market_hits": sum(1 for i in market if i.market_hit),
        "market_expected_hits": sum(i.market_top[1] for i in market if i.market_top),
        "tiers": tiers,
    }


def review_day(session: Session, settings: Settings, day: date, tz: str) -> ReviewDay:
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    provider = settings.data_provider
    fixtures = queries.fixtures_between(session, start, end, provider)
    preds = queries.predictions_before_kickoff(session, [f.id for f in fixtures])
    items = []
    for f in fixtures:
        p = preds.get(f.id)
        items.append(
            ReviewItem(
                fixture=f,
                prediction=p,
                model=model_probabilities(p) if p else None,
                market=market_view(p.odds_snapshot).fair if p else None,
                actual=actual_outcome(f),
            )
        )
    verified = verified_league_ids(session, provider)
    demo = provider == "mock"
    in_scope = [i for i in items if demo or i.fixture.league.provider_id in verified]
    pick = session.scalars(
        select(DailyPick)
        .where(DailyPick.provider == provider, DailyPick.pick_date == day)
        .order_by(DailyPick.revision.desc())
        .limit(1)
    ).first()
    return ReviewDay(
        day=day,
        tz=tz,
        start_utc=start.astimezone(ZoneInfo("UTC")),
        end_utc=end.astimezone(ZoneInfo("UTC")),
        items=items,
        verified=verified,
        demo=demo,
        pick=pick,
        summaries={"verified": summarize(in_scope), "all": summarize(items)},
    )


def pick_result(pick: DailyPick) -> dict[str, Any]:
    status = effective_status(pick)
    settled = next((e for e in pick.events if e.event == "settled"), None)
    return {
        "status": status,
        "outcome": pick.outcome,
        "probability": pick.probability,
        "fixture_id": pick.fixture_id,
        "hit": settled.hit if settled else None,
    }
