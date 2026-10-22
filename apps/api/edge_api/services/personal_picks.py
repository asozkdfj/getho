"""The user's own picks: storage, revisions and the frozen pre-match analysis
(docs/qa/2026-10-21-personal-pick-review-spec.md, stage R1).

Rules
- Every change is a new revision row (append-only table); the same
  ``idempotency_key`` sent again stores nothing and returns the stored pick.
- The server decides ``source_type`` from its own clock: a revision stored
  before kickoff is a prospective record, anything stored later is a
  retrospective self-report. The user cannot claim otherwise.
- The analysis is computed once, when the revision is stored, from rows the
  database held at the decision time (created and captured by then). It is
  saved with the revision and never recomputed, so a later prediction, odds
  move, line-up or result cannot change it.
- Nothing missing is filled in: no prediction, no odds, no entry odds or
  absences not checked are reported as missing, never as 0 or "normal".
- No combined risk score. Each number has its formula in the field description.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edge_api.db.models import (
    Fixture,
    FixtureObservation,
    FixtureStatus,
    PersonalPick,
    Prediction,
    TeamNewsKind,
)
from edge_api.schemas import (
    PersonalPickDetailOut,
    PersonalPickFields,
    PersonalPickIn,
    PersonalPickListOut,
    PersonalPickOut,
    PersonalPickRevisionIn,
    PersonalPickRevisionOut,
    PickAnalysisOut,
    PickMarketViewOut,
    PickMissingOut,
    PickModelViewOut,
    PickOutcomeProbabilityOut,
    PickPriceViewOut,
    PickTeamNewsOut,
    PickTeamNewsSideOut,
    TeamNewsSideOut,
    TeamOut,
)
from edge_api.services.analysis import (
    market_view,
    model_probabilities,
    odds_for,
    to_probabilities_out,
)
from edge_api.services.leagues import league_ref, verified_league_ids
from edge_api.services.shadow import market_odds_at
from edge_api.services.team_news import latest_snapshots, team_news
from edge_ml.core import Outcome

ANALYSIS_VERSION = "personal-pick-r1-2026-10-21"
STALE_ODDS = timedelta(hours=24)
SOURCE_TYPES = ("prospective_record", "retrospective_self_report")


class PickError(ValueError):
    """Invalid request (HTTP 422)."""


class PickNotFoundError(LookupError):
    """Unknown fixture or pick (HTTP 404)."""


class PickConflictError(RuntimeError):
    """Idempotency key reused with another request, or a stale base revision (HTTP 409)."""


def prediction_known_at(session: Session, fixture_id: int, at: datetime) -> Prediction | None:
    """Newest prediction that was stored by ``at`` and built only from inputs known
    by then (what the service could have shown at the decision)."""
    return session.scalars(
        select(Prediction)
        .where(
            Prediction.fixture_id == fixture_id,
            Prediction.created_at <= at,
            Prediction.input_data_as_of <= at,
        )
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(1)
    ).first()


def _model_view(prediction: Prediction, selection: Outcome) -> PickModelViewOut:
    probs = model_probabilities(prediction)
    p = probs.get(selection)
    top = max(Outcome, key=probs.get)
    return PickModelViewOut(
        prediction_id=prediction.id,
        model_version=prediction.model_version.version,
        prediction_created_at=prediction.created_at,
        input_data_as_of=prediction.input_data_as_of,
        probabilities=to_probabilities_out(probs),
        selection_probability=p,
        failure_probability=1.0 - p,
        failure_outcomes=[
            PickOutcomeProbabilityOut(outcome=o, probability=probs.get(o))
            for o in Outcome
            if o != selection
        ],
        top_outcome=top,
        top_probability=probs.get(top),
        agrees_with_top=top == selection,
    )


def _side(side: TeamNewsSideOut | None, name: str) -> PickTeamNewsSideOut:
    if side is None:
        return PickTeamNewsSideOut(team_name=name, absences_status="unknown", regulars_known=False)
    return PickTeamNewsSideOut(
        team_name=side.team_name,
        absences_status=side.absences_status,
        absences=[
            f"{a.name} ({'결장' if a.status == 'out' else '출전 불투명'})" for a in side.absences
        ],
        absences_captured_at=side.absences_captured_at,
        lineup_captured_at=side.lineup_captured_at,
        missing_regulars=[m.name for m in side.missing_regulars],
        regulars_known=side.regulars_known,
    )


def analyse(
    session: Session,
    fixture: Fixture,
    fields: PersonalPickFields,
    *,
    decision_at: datetime,
    computed_at: datetime,
    bookmaker: str,
    provider: str,
) -> PickAnalysisOut:
    """The pre-match analysis of one selection from what was known at ``decision_at``."""
    selection = fields.selection
    warnings: list[str] = []
    missing: list[PickMissingOut] = []

    prediction = prediction_known_at(session, fixture.id, decision_at)
    model = _model_view(prediction, selection) if prediction else None
    if model is None:
        missing.append(PickMissingOut(item="model", reason="no_prediction_known_at_decision"))

    snapshot = market_odds_at(session, [fixture.id], bookmaker, decision_at).get(fixture.id)
    market = None
    if snapshot is None:
        missing.append(PickMissingOut(item="market", reason="no_odds_known_at_decision"))
    else:
        fair = market_view(snapshot).fair
        age = decision_at - snapshot.captured_at
        market = PickMarketViewOut(
            odds_snapshot_id=snapshot.id,
            bookmaker=snapshot.bookmaker,
            captured_at=snapshot.captured_at,
            age_minutes=round(age.total_seconds() / 60, 1),
            selection_odds=odds_for(snapshot, selection),
            fair_probabilities=to_probabilities_out(fair),
            selection_fair_probability=fair.get(selection),
            model_minus_market=(
                model.selection_probability - fair.get(selection) if model else None
            ),
        )
        if age > STALE_ODDS:
            warnings.append("market_odds_older_than_24h")

    price = None
    if fields.entry_odds is None:
        missing.append(PickMissingOut(item="entry_odds", reason="not_entered"))
    else:
        d = float(fields.entry_odds)
        price = PickPriceViewOut(
            entry_odds=d,
            break_even_probability=1.0 / d,
            model_assumption_return=(model.selection_probability * d - 1.0) if model else None,
            market_assumption_return=(
                market.selection_fair_probability * d - 1.0 if market else None
            ),
        )
    if fields.user_probability is None:
        missing.append(PickMissingOut(item="user_probability", reason="not_entered"))

    news = team_news(session, fixture, decision_at)
    snapshot_ids = sorted(
        s.id
        for kind in (TeamNewsKind.LINEUP, TeamNewsKind.ABSENCES)
        for s in latest_snapshots(session, fixture.id, kind, decision_at).values()
    )
    sides = {
        "home": _side(news.home if news else None, fixture.home_team.name),
        "away": _side(news.away if news else None, fixture.away_team.name),
    }
    for key, side in sides.items():
        if side.absences_status == "unknown":
            missing.append(PickMissingOut(item=f"absences_{key}", reason="not_checked"))
            warnings.append(f"absences_unknown_{key}")

    verified = fixture.league.provider_id in verified_league_ids(
        session, provider, as_of=decision_at
    )
    if not verified:
        warnings.append("league_not_verified")
    if model and not model.agrees_with_top:
        warnings.append("selection_differs_from_model_top")

    return PickAnalysisOut(
        version=ANALYSIS_VERSION,
        as_of=decision_at,
        computed_at=computed_at,
        selection=selection,
        home_team=fixture.home_team.name,
        away_team=fixture.away_team.name,
        league_name=fixture.league.name,
        league_verified=verified,
        kickoff_at=fixture.kickoff_at,
        fixture_status=fixture.status,
        model=model,
        market=market,
        price=price,
        team_news=PickTeamNewsOut(
            lineups_announced=bool(news and news.lineups_announced),
            home=sides["home"],
            away=sides["away"],
            snapshot_ids=snapshot_ids,
        ),
        warnings=warnings,
        missing=missing,
    )


def _request_hash(payload: dict[str, object]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _clean_reason(text: str | None) -> str | None:
    """Stored as plain text (the page escapes it); control characters dropped."""
    if text is None:
        return None
    cleaned = "".join(ch for ch in text if ch in "\n\t" or ch.isprintable()).strip()
    return cleaned or None


def _decision_time(
    fields: PersonalPickFields, now: datetime, kickoff_at: datetime
) -> tuple[datetime, str]:
    decision_at = fields.decision_at or now
    if decision_at > now:
        raise PickError("결정 시각이 미래입니다.")
    if decision_at >= kickoff_at:
        raise PickError(
            "결정 시각이 경기 시작 이후입니다. 경기 전 1X2만 기록할 수 있어요 "
            "(지난 경기는 경기 전 결정 시각을 입력하세요)."
        )
    return decision_at, ("user_stated" if fields.decision_at else "server_clock")


def _check_not_started(session: Session, fixture: Fixture, now: datetime) -> None:
    """Before kickoff a pick is a pre-match record only if nothing says the match
    already started: the fixture must be scheduled now, and no observation stored
    by now may show it live, finished or with a score (Codex QA PICK-STATE-1). A contradiction
    (bad provider data, a schedule not yet corrected) is refused, not recorded."""
    if fixture.status != FixtureStatus.SCHEDULED.value:
        raise PickError(
            f"경기 상태({fixture.status})와 시작 시각이 맞지 않아 경기 전 기록으로 "
            "저장할 수 없어요. 일정·상태가 정정된 뒤 다시 시도하세요."
        )
    started = session.scalars(
        select(FixtureObservation.id)
        .where(
            FixtureObservation.fixture_id == fixture.id,
            FixtureObservation.created_at <= now,
            # a postponed match moved back to the schedule is fine; one seen live
            # or finished, or with a score, has started
            FixtureObservation.status.in_([FixtureStatus.LIVE.value, FixtureStatus.FINISHED.value])
            | FixtureObservation.home_score.is_not(None)
            | FixtureObservation.away_score.is_not(None),
        )
        .limit(1)
    ).first()
    if started is not None:
        raise PickError(
            "이 경기는 시작했거나 결과가 기록된 적이 있어 경기 전 기록으로 저장할 수 없어요."
        )


def _by_idempotency_key(session: Session, key: str) -> PersonalPick | None:
    return session.scalars(select(PersonalPick).where(PersonalPick.idempotency_key == key)).first()


def _replay(session: Session, key: str, request_sha256: str) -> PersonalPick | None:
    stored = _by_idempotency_key(session, key)
    if stored is None:
        return None
    if stored.request_sha256 != request_sha256:
        raise PickConflictError("같은 요청 키로 다른 내용이 이미 저장되어 있습니다.")
    return stored


def _insert(session: Session, row: PersonalPick, key: str, request_sha256: str) -> PersonalPick:
    """Insert one revision; a concurrent duplicate resolves to the stored row."""
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        stored = _replay(session, key, request_sha256)
        if stored is not None:
            return stored
        raise PickConflictError(
            "다른 변경이 먼저 저장되었습니다. 새로고침 후 다시 시도하세요."
        ) from exc
    return row


def _new_row(
    session: Session,
    fixture: Fixture,
    fields: PersonalPickFields,
    *,
    pick_key: str,
    revision: int,
    key: str,
    request_sha256: str,
    now: datetime,
    bookmaker: str,
    provider: str,
    not_before: datetime | None = None,
) -> PersonalPick:
    decision_at, evidence = _decision_time(fields, now, fixture.kickoff_at)
    if now < fixture.kickoff_at:
        _check_not_started(session, fixture, now)
    if not_before is not None and decision_at < not_before:
        raise PickError("수정의 결정 시각은 이전 기록의 결정 시각보다 앞설 수 없습니다.")
    analysis = analyse(
        session,
        fixture,
        fields,
        decision_at=decision_at,
        computed_at=now,
        bookmaker=bookmaker,
        provider=provider,
    )
    return PersonalPick(
        pick_key=pick_key,
        revision=revision,
        idempotency_key=key,
        request_sha256=request_sha256,
        fixture_id=fixture.id,
        kickoff_at=fixture.kickoff_at,
        market_type="1X2",
        selection=fields.selection.value,
        decision_at=decision_at,
        time_evidence=evidence,
        recorded_at=now,
        source_type="prospective_record" if now < fixture.kickoff_at else SOURCE_TYPES[1],
        self_reported_purchase=fields.self_reported_purchase,
        entry_odds=None if fields.entry_odds is None else Decimal(str(fields.entry_odds)),
        stake_krw=fields.stake_krw,
        user_probability=fields.user_probability,
        user_reason=_clean_reason(fields.user_reason),
        analysis_version=ANALYSIS_VERSION,
        analysis=analysis.model_dump(mode="json"),
    )


def _fields_payload(fields: PersonalPickFields) -> dict[str, object]:
    return fields.model_dump(mode="json", exclude={"idempotency_key"})


def create_pick(
    session: Session, request: PersonalPickIn, *, now: datetime, bookmaker: str, provider: str
) -> PersonalPickDetailOut:
    request_sha256 = _request_hash({"op": "create", **_fields_payload(request)})
    stored = _replay(session, request.idempotency_key, request_sha256)
    if stored is None:
        fixture = session.get(Fixture, request.fixture_id)
        if fixture is None or fixture.provider != provider:
            raise PickNotFoundError("경기를 찾을 수 없습니다.")
        row = _new_row(
            session,
            fixture,
            request,
            pick_key=str(uuid.uuid4()),
            revision=1,
            key=request.idempotency_key,
            request_sha256=request_sha256,
            now=now,
            bookmaker=bookmaker,
            provider=provider,
        )
        stored = _insert(session, row, request.idempotency_key, request_sha256)
        session.commit()
    return get_pick(session, stored.pick_key, provider=provider)


def revise_pick(
    session: Session,
    pick_id: str,
    request: PersonalPickRevisionIn,
    *,
    now: datetime,
    bookmaker: str,
    provider: str,
) -> PersonalPickDetailOut:
    request_sha256 = _request_hash({"op": "revise", "pick_id": pick_id, **_fields_payload(request)})
    stored = _replay(session, request.idempotency_key, request_sha256)
    if stored is None:
        history = _revisions(session, pick_id)
        if not history or history[-1].fixture.provider != provider:
            raise PickNotFoundError("기록을 찾을 수 없습니다.")
        last = history[-1]
        if request.base_revision != last.revision:
            raise PickConflictError(
                f"기록이 이미 {last.revision}번째 수정본으로 바뀌었습니다. 새로고침 후 다시 "
                "시도하세요."
            )
        row = _new_row(
            session,
            last.fixture,
            request,
            pick_key=pick_id,
            revision=last.revision + 1,
            key=request.idempotency_key,
            request_sha256=request_sha256,
            now=now,
            bookmaker=bookmaker,
            provider=provider,
            not_before=last.decision_at,
        )
        stored = _insert(session, row, request.idempotency_key, request_sha256)
        session.commit()
    return get_pick(session, stored.pick_key, provider=provider)


def _revisions(session: Session, pick_id: str) -> Sequence[PersonalPick]:
    return session.scalars(
        select(PersonalPick).where(PersonalPick.pick_key == pick_id).order_by(PersonalPick.revision)
    ).all()


def _revision_out(row: PersonalPick) -> PersonalPickRevisionOut:
    return PersonalPickRevisionOut(
        revision=row.revision,
        recorded_at=row.recorded_at,
        decision_at=row.decision_at,
        time_evidence=row.time_evidence,  # type: ignore[arg-type]
        source_type=row.source_type,  # type: ignore[arg-type]
        selection=Outcome(row.selection),
        entry_odds=None if row.entry_odds is None else float(row.entry_odds),
        stake_krw=row.stake_krw,
        user_probability=row.user_probability,
        user_reason=row.user_reason,
        self_reported_purchase=row.self_reported_purchase,
        analysis=PickAnalysisOut.model_validate(row.analysis),
    )


def _pick_out(history: Sequence[PersonalPick], verified: frozenset[str]) -> PersonalPickOut:
    last = history[-1]
    fixture = last.fixture
    prospective = [r.revision for r in history if r.source_type == "prospective_record"]
    return PersonalPickOut(
        pick_id=last.pick_key,
        fixture_id=fixture.id,
        league=league_ref(fixture.league, verified),
        home_team=TeamOut.model_validate(fixture.home_team),
        away_team=TeamOut.model_validate(fixture.away_team),
        kickoff_at=fixture.kickoff_at,
        status=fixture.status,
        home_score=fixture.home_score,
        away_score=fixture.away_score,
        current=_revision_out(last),
        revisions=len(history),
        prospective_revision=prospective[-1] if prospective else None,
        edited_after_kickoff=bool(prospective) and last.source_type != "prospective_record",
    )


def get_pick(session: Session, pick_id: str, *, provider: str) -> PersonalPickDetailOut:
    history = _revisions(session, pick_id)
    if not history or history[-1].fixture.provider != provider:
        raise PickNotFoundError("기록을 찾을 수 없습니다.")
    out = _pick_out(history, verified_league_ids(session, provider))
    return PersonalPickDetailOut(**out.model_dump(), history=[_revision_out(r) for r in history])


def list_picks(session: Session, *, provider: str, limit: int = 200) -> PersonalPickListOut:
    newest = (
        select(PersonalPick.pick_key, func.max(PersonalPick.recorded_at).label("last"))
        .join(Fixture, Fixture.id == PersonalPick.fixture_id)
        .where(Fixture.provider == provider)
        .group_by(PersonalPick.pick_key)
        .order_by(func.max(PersonalPick.recorded_at).desc(), PersonalPick.pick_key)
        .limit(limit)
        .subquery()
    )
    rows = session.scalars(
        select(PersonalPick)
        .join(newest, newest.c.pick_key == PersonalPick.pick_key)
        .order_by(newest.c.last.desc(), PersonalPick.pick_key, PersonalPick.revision)
    ).all()
    grouped: dict[str, list[PersonalPick]] = {}
    for row in rows:
        grouped.setdefault(row.pick_key, []).append(row)
    verified = verified_league_ids(session, provider)
    picks = [_pick_out(h, verified) for h in grouped.values()]
    counts = Counter(p.current.source_type for p in picks)
    return PersonalPickListOut(picks=picks, counts={s: counts.get(s, 0) for s in SOURCE_TYPES})
