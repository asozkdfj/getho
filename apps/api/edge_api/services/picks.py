"""Today's Pick: decide once per pick day, freeze the decision, settle later.

A pick day runs from the publish hour (pick_tz) to the same hour the next day,
e.g. 09:00 KST -> 09:00 KST, so European evening matches (early morning in
Korea) belong to the pick published the morning before. Between midnight and
the publish hour the previous day's pick is still the current one.

Flow
1. ``get_today_pick``: the current pick day's decision is published
   (idempotently) the first time anyone asks or the pipeline runs.
2. ``publish_daily_pick``: candidates = the pick day's upcoming fixtures of
   the active provider -> data-quality gate -> shared selection rule
   (``edge_ml.picks.select_pick``) with the backtested threshold. The row is
   written with INSERT ... ON CONFLICT DO NOTHING on (provider, day, revision),
   so concurrent requests, restarts and job re-runs cannot publish twice.
3. ``settle_daily_picks``: when the match is finished (or cancelled/postponed),
   append a ``settled``/``voided`` event. The published row is never changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import (
    DailyPick,
    DailyPickEvent,
    DailyPickStatus,
    Fixture,
    FixtureStatus,
    ModelEvaluation,
)
from edge_api.services import queries
from edge_api.services.leagues import scoped_league_ids
from edge_api.services.quality import assess, last_successful_run
from edge_ml.core import Outcome, Probabilities1X2
from edge_ml.metrics import wilson_interval
from edge_ml.model import FEATURE_SET, MODEL_VERSION
from edge_ml.picks import PickCandidate, best_outcome, select_pick

# What the production model actually uses - explanations may only cite these.
MODEL_FACTORS = ["team_strength_elo", "attack_defence_strength", "home_advantage"]


@dataclass(frozen=True, slots=True)
class LocalDay:
    day: date
    tz: str
    start_utc: datetime
    end_utc: datetime
    publish_at: datetime


def local_day(now: datetime, settings: Settings) -> LocalDay:
    """The pick day containing ``now``: [publish hour, publish hour next day)."""
    zone = ZoneInfo(settings.pick_tz)
    shifted = now.astimezone(zone) - timedelta(hours=settings.pick_publish_hour)
    day = shifted.date()
    start = datetime.combine(day, time(settings.pick_publish_hour), tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time(settings.pick_publish_hour), tzinfo=zone)
    return LocalDay(
        day=day,
        tz=settings.pick_tz,
        start_utc=start.astimezone(ZoneInfo("UTC")),
        end_utc=end.astimezone(ZoneInfo("UTC")),
        publish_at=start.astimezone(ZoneInfo("UTC")),
    )


def _policy(settings: Settings) -> dict[str, Any]:
    return {
        "min_probability": settings.pick_min_probability,
        "tz": settings.pick_tz,
        "publish_hour": settings.pick_publish_hour,
        # candidates kick off between the publish hour and the same hour next day
        "window": "publish_hour_to_next_day_publish_hour",
        "replace_on_void": settings.pick_replace_on_void,
        "odds_max_age_hours": settings.odds_max_age,
        "ingest_max_age_hours": settings.ingest_max_age_hours,
        "min_team_matches": settings.min_team_matches,
    }


def backtest_reference(session: Session, threshold: float) -> dict[str, Any] | None:
    """Historical performance of the daily rule at this threshold (current model)."""
    ev = session.scalars(
        select(ModelEvaluation)
        .where(
            ModelEvaluation.model_version == MODEL_VERSION,
            ModelEvaluation.feature_set == FEATURE_SET,
        )
        .order_by(ModelEvaluation.created_at.desc(), ModelEvaluation.id.desc())
        .limit(1)
    ).first()
    if ev is None:
        return None
    # Prefer the replay with the service's timing (decided at the publish hour, later
    # kickoffs only); the whole-day replay overstates how often a pick is published.
    block = ev.report.get("daily_pick_timing_proxy") or ev.report.get("daily_pick_backtest") or {}
    rows = [r for r in block.get("rows", []) if r.get("days_with_pick")]
    eligible = [r for r in rows if r["min_probability"] <= threshold + 1e-9]
    if not eligible:
        return None
    row = max(eligible, key=lambda r: r["min_probability"])
    names = {lg.get("code"): lg.get("name") for lg in ev.report.get("leagues") or []}
    return {
        "evaluation_id": ev.id,
        "dataset": ev.dataset,
        "period": (ev.report.get("split") or {}).get("test"),
        "threshold": row["min_probability"],
        "days_with_pick": row["days_with_pick"],
        "match_days": row["match_days"],
        "hit_rate": row["hit_rate"],
        "hit_rate_ci": row["hit_rate_ci"],
        "mean_pick_probability": row["mean_pick_probability"],
        "leagues": [names.get(c, c) for c in block.get("leagues") or []],
        "decision_hour": block.get("decision_hour"),
    }


def _insert_pick(session: Session, values: dict[str, Any]) -> DailyPick:
    stmt = (
        insert(DailyPick)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_daily_picks_day_revision")
    )
    session.execute(stmt)
    session.flush()
    return session.scalars(
        select(DailyPick).where(
            DailyPick.provider == values["provider"],
            DailyPick.pick_date == values["pick_date"],
            DailyPick.revision == values["revision"],
        )
    ).one()


def eligible_league_ids(session: Session, settings: Settings) -> frozenset[str] | None:
    """Provider league ids the pick may come from (None = every predicted league)."""
    return scoped_league_ids(session, settings.data_provider, settings.pick_leagues)


def publish_daily_pick(
    session: Session, settings: Settings, now: datetime, revision: int = 1
) -> DailyPick:
    """Decide and freeze the pick for ``now``'s local day (idempotent)."""
    ld = local_day(now, settings)
    provider = settings.data_provider
    existing = session.scalars(
        select(DailyPick).where(
            DailyPick.provider == provider,
            DailyPick.pick_date == ld.day,
            DailyPick.revision == revision,
        )
    ).first()
    if existing is not None:
        return existing

    all_fixtures = queries.fixtures_between(session, ld.start_utc, ld.end_utc, provider)
    scope = eligible_league_ids(session, settings)
    fixtures = [f for f in all_fixtures if scope is None or f.league.provider_id in scope]
    preds = queries.latest_predictions_by_fixture(session, [f.id for f in fixtures])
    last_run = last_successful_run(session, provider)

    considered: list[dict[str, Any]] = []
    candidates: list[PickCandidate] = []
    quality_by_fixture: dict[int, list[dict[str, Any]]] = {}
    for f in fixtures:
        p = preds.get(f.id)
        report = assess(f, p, now=now, settings=settings, last_run=last_run)
        checks = [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in report.checks]
        quality_by_fixture[f.id] = checks
        entry: dict[str, Any] = {
            "fixture_id": f.id,
            "league": f.league.name,
            "home": f.home_team.name,
            "away": f.away_team.name,
            "kickoff_at": f.kickoff_at.isoformat(),
            "excluded_reasons": [c.name for c in report.failed],
        }
        if p is not None:
            probs = Probabilities1X2(p.probability_home, p.probability_draw, p.probability_away)
            outcome, prob = best_outcome(probs)
            entry.update(best_outcome=outcome.value, best_probability=prob)
            if report.ok:
                if prob >= settings.pick_min_probability:
                    candidates.append(PickCandidate(str(f.id), f.kickoff_at, probs))
                else:
                    entry["excluded_reasons"].append("below_min_probability")
        entry["eligible"] = not entry["excluded_reasons"]
        considered.append(entry)

    choice = select_pick(candidates, settings.pick_min_probability)
    evidence: dict[str, Any] = {
        "is_demo": provider == "mock",
        "threshold": settings.pick_min_probability,
        "window_utc": [ld.start_utc.isoformat(), ld.end_utc.isoformat()],
        "matches_today": len(all_fixtures),
        "league_scope": settings.pick_leagues,
        "eligible_leagues": sorted(scope) if scope is not None else "all",
        "matches_in_scope": len(fixtures),
        "candidates": considered,
        "backtest": backtest_reference(session, settings.pick_min_probability),
        "model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "factors_used": MODEL_FACTORS,
    }
    values: dict[str, Any] = {
        "provider": provider,
        "pick_date": ld.day,
        "tz": ld.tz,
        "revision": revision,
        "evidence": evidence,
        "policy": _policy(settings),
    }
    if choice is None:
        values["status"] = (
            DailyPickStatus.NO_MATCHES.value
            if not all_fixtures
            else DailyPickStatus.NO_QUALIFYING_MATCH.value
        )
        return _insert_pick(session, values)

    fixture_id = int(choice.candidate.key)
    p = preds[fixture_id]
    features = p.features or {}
    evidence["chosen"] = {
        "fixture_id": fixture_id,
        "outcome": choice.outcome.value,
        "probability": choice.probability,
        "probabilities": {
            "home": p.probability_home,
            "draw": p.probability_draw,
            "away": p.probability_away,
        },
        "expected_goals": {"home": p.expected_goals_home, "away": p.expected_goals_away},
        "rank_reason": "highest model probability among today's eligible matches",
        "calibrator": features.get("calibrator", "identity"),
        "features": {
            k: features.get(k)
            for k in (
                "elo_home",
                "elo_away",
                "elo_diff_incl_hfa",
                "attack_home",
                "defence_home",
                "attack_away",
                "defence_away",
                "prior_home",
                "prior_away",
                "matches_home",
                "matches_away",
            )
        },
        "quality_checks": quality_by_fixture[fixture_id],
        "odds_snapshot_id": p.market_odds_snapshot_id,
    }
    values.update(
        status=DailyPickStatus.PUBLISHED.value,
        fixture_id=fixture_id,
        prediction_id=p.id,
        model_version_id=p.model_version_id,
        outcome=choice.outcome.value,
        probability=choice.probability,
        input_data_as_of=p.input_data_as_of,
    )
    return _insert_pick(session, values)


def _latest_pick(session: Session, provider: str, day: date) -> DailyPick | None:
    return session.scalars(
        select(DailyPick)
        .where(DailyPick.provider == provider, DailyPick.pick_date == day)
        .order_by(DailyPick.revision.desc())
        .limit(1)
    ).first()


@dataclass(slots=True)
class TodayPick:
    day: LocalDay
    pick: DailyPick | None
    status: str
    events: list[DailyPickEvent] = field(default_factory=list)


def effective_status(pick: DailyPick) -> str:
    kinds = {e.event for e in pick.events}
    if "voided" in kinds:
        return "voided"
    if "settled" in kinds:
        return "settled"
    return pick.status


def get_today_pick(
    session: Session, settings: Settings, now: datetime, publish_if_due: bool = True
) -> TodayPick:
    ld = local_day(now, settings)
    pick = _latest_pick(session, settings.data_provider, ld.day)
    if pick is None and publish_if_due and now >= ld.publish_at:
        pick = publish_daily_pick(session, settings, now)
        session.commit()
    if pick is None:
        return TodayPick(ld, None, "scheduled")
    return TodayPick(ld, pick, effective_status(pick), list(pick.events))


def _outcome_of(f: Fixture) -> Outcome | None:
    if f.home_score is None or f.away_score is None:
        return None
    if f.home_score > f.away_score:
        return Outcome.HOME
    return Outcome.DRAW if f.home_score == f.away_score else Outcome.AWAY


def _moved_out_of_window(pick: DailyPick, fixture: Fixture) -> bool:
    """True when the fixture now kicks off outside the window the pick was chosen
    from (recorded in its evidence when it was published)."""
    window = (pick.evidence or {}).get("window_utc")
    if not window or len(window) != 2:
        return False
    start, end = (datetime.fromisoformat(w) for w in window)
    return not (start <= fixture.kickoff_at < end)


def settle_daily_picks(session: Session, settings: Settings, now: datetime) -> dict[str, int]:
    """Append settled/voided events for published picks whose match has resolved."""
    counts = {"settled": 0, "voided": 0, "republished": 0}
    picks = session.scalars(
        select(DailyPick).where(
            DailyPick.provider == settings.data_provider,
            DailyPick.status == DailyPickStatus.PUBLISHED.value,
        )
    ).all()
    for pick in picks:
        if pick.events or pick.fixture is None:
            continue
        f = pick.fixture
        if f.status in (FixtureStatus.CANCELLED.value, FixtureStatus.POSTPONED.value):
            values = {"event": "voided", "reason": f"fixture {f.status}"}
        elif f.status == FixtureStatus.SCHEDULED.value and _moved_out_of_window(pick, f):
            # rescheduled to a time outside the pick day: the pick's match did not happen
            values = {"event": "voided", "reason": "fixture rescheduled"}
        elif f.status == FixtureStatus.FINISHED.value and (actual := _outcome_of(f)):
            values = {
                "event": "settled",
                "actual_outcome": actual.value,
                "hit": actual.value == pick.outcome,
            }
        else:
            continue
        inserted = session.execute(
            insert(DailyPickEvent)
            .values(pick_id=pick.id, **values)
            .on_conflict_do_nothing(constraint="uq_daily_pick_events_one_per_kind")
            .returning(DailyPickEvent.id)
        ).scalar_one_or_none()
        session.expire(pick, ["events"])  # keep the relationship in sync
        if inserted is None:
            continue  # recorded by an earlier or concurrent run
        counts[values["event"]] += 1
        if values["event"] == "voided" and settings.pick_replace_on_void:
            ld = local_day(now, settings)
            if pick.pick_date == ld.day and now < ld.end_utc:
                publish_daily_pick(session, settings, now, revision=pick.revision + 1)
                counts["republished"] += 1
    session.flush()
    return counts


def pick_history(session: Session, settings: Settings, limit: int) -> dict[str, Any]:
    picks = session.scalars(
        select(DailyPick)
        .where(DailyPick.provider == settings.data_provider)
        .order_by(DailyPick.pick_date.desc(), DailyPick.revision.desc())
        .limit(limit)
    ).all()
    all_published = session.scalars(
        select(DailyPick).where(
            DailyPick.provider == settings.data_provider,
            DailyPick.status == DailyPickStatus.PUBLISHED.value,
        )
    ).all()
    settled = [
        (p.probability, e.hit)
        for p in all_published
        for e in p.events
        if e.event == "settled" and p.probability is not None
    ]
    hits = sum(1 for _, h in settled if h)
    n = len(settled)
    lo, hi = wilson_interval(hits, n)
    summary = {
        "published": len(all_published),
        "settled": n,
        "voided": sum(1 for p in all_published if any(e.event == "voided" for e in p.events)),
        "pending": sum(1 for p in all_published if not p.events),
        "hits": hits,
        "hit_rate": hits / n if n else None,
        "hit_rate_ci": [lo, hi] if n else None,
        "mean_probability": sum(p for p, _ in settled) / n if n else None,
    }
    return {"picks": list(picks), "summary": summary}
