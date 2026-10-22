"""Collection alerts: notice when the always-on server stops doing its job.

Checks (each one is firing or not at ``now``):
- ``pipeline_failing``: the last N pipeline runs all failed (N =
  ``alert_consecutive_failures``).
- ``pipeline_stale``: no successful run for more than ``ingest_max_age_hours``
  (the same limit the data badge uses), or none at all.
- ``pick_missing``: the pick day's decision time plus ``alert_pick_grace_minutes``
  has passed and no Today's Pick row exists for that day (not even "no
  qualifying match"): the decision itself did not run.

A message goes out only when a check changes state (firing -> resolved or
back), when the last message for a firing check was not delivered, or as a
reminder every ``alert_remind_hours`` while it keeps firing. Every message is
recorded in ``alert_events`` (append-only); the latest row per check is its
state. Without a channel configured nothing is recorded (dry run).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import AlertEvent, DailyPick, IngestionRun
from edge_api.services.picks import local_day

PREFIX = "[EPL Edge Lab]"
SCAN_RUNS = 50

# (delivered, error) for one message
Sender = Callable[[str], tuple[bool, str | None]]


@dataclass(frozen=True, slots=True)
class Condition:
    key: str
    firing: bool
    message: str  # what is wrong (used while firing)
    resolved: str  # what is fine again
    detail: dict[str, Any] = field(default_factory=dict)


def redact(text: str | None, limit: int = 300) -> str:
    """Error text for a phone message: long tokens (keys, hashes) masked, truncated."""
    if not text:
        return ""
    masked = re.sub(r"[A-Za-z0-9_\-]{24,}", "***", text)
    return masked if len(masked) <= limit else masked[: limit - 1] + "…"


def _runs(session: Session, provider: str) -> list[IngestionRun]:
    return list(
        session.scalars(
            select(IngestionRun)
            .where(IngestionRun.provider == provider)
            .order_by(IngestionRun.finished_at.desc(), IngestionRun.id.desc())
            .limit(SCAN_RUNS)
        )
    )


def evaluate(session: Session, settings: Settings, now: datetime) -> list[Condition]:
    provider = settings.data_provider
    runs = _runs(session, provider)
    streak = 0
    for run in runs:
        if run.status != "failed":
            break
        streak += 1
    last_ok = next((r for r in runs if r.status == "success"), None)
    if last_ok is None:  # older than the scanned window, or never
        last_ok = session.scalars(
            select(IngestionRun)
            .where(IngestionRun.provider == provider, IngestionRun.status == "success")
            .order_by(IngestionRun.finished_at.desc())
            .limit(1)
        ).first()
    age_h = (now - last_ok.finished_at).total_seconds() / 3600 if last_ok else None

    day = local_day(now, settings)
    due = day.publish_at + timedelta(minutes=settings.alert_pick_grace_minutes)
    decided = (
        session.scalars(
            select(DailyPick.id)
            .where(DailyPick.provider == provider, DailyPick.pick_date == day.day)
            .limit(1)
        ).first()
        is not None
    )

    failing = streak >= settings.alert_consecutive_failures
    stale = age_h is None or age_h > settings.ingest_max_age_hours
    return [
        Condition(
            key="pipeline_failing",
            firing=failing,
            message=f"수집이 {streak}회 연속 실패했어요. 마지막 오류: "
            f"{redact(runs[0].error) if failing and runs else '-'}",
            resolved="수집이 다시 성공했어요.",
            detail={"consecutive_failures": streak},
        ),
        Condition(
            key="pipeline_stale",
            firing=stale,
            message=(
                "성공한 수집 기록이 없어요."
                if age_h is None
                else f"마지막 성공 수집이 {age_h:.1f}시간 전이에요 "
                f"(기준 {settings.ingest_max_age_hours:g}시간). worker가 멈췄는지 확인하세요."
            ),
            resolved="수집이 다시 제때 되고 있어요.",
            detail={"last_success_age_hours": None if age_h is None else round(age_h, 2)},
        ),
        Condition(
            key="pick_missing",
            firing=now >= due and not decided,
            message=f"{day.day} 오늘의 픽 결정이 아직 없어요 "
            f"(결정 {settings.pick_publish_hour:02d}:00 {settings.pick_tz} + "
            f"{settings.alert_pick_grace_minutes}분 지남).",
            resolved=f"{day.day} 오늘의 픽 결정이 기록됐어요.",
            detail={"pick_date": day.day.isoformat()},
        ),
    ]


def _latest(session: Session, key: str) -> AlertEvent | None:
    return session.scalars(
        select(AlertEvent)
        .where(AlertEvent.key == key)
        .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
        .limit(1)
    ).first()


def _action(c: Condition, last: AlertEvent | None, now: datetime, remind: timedelta) -> str | None:
    if c.firing:
        if last is None or last.state == "resolved" or not last.delivered:
            return "firing"
        return "firing" if now - last.created_at >= remind else None
    if last is not None and (last.state == "firing" or not last.delivered):
        return "resolved"
    return None


def _text(c: Condition, state: str, now: datetime, tz: str) -> str:
    stamp = now.astimezone(ZoneInfo(tz)).strftime("%m-%d %H:%M")
    if state == "firing":
        return f"{PREFIX} ⚠️ {c.message} ({stamp} {tz})"
    return f"{PREFIX} ✅ 해결: {c.resolved} ({stamp} {tz})"


def check(
    session: Session,
    settings: Settings,
    now: datetime,
    send: Sender | None,
    channel: str = "telegram",
) -> list[dict[str, Any]]:
    """Evaluate every check and send what changed. ``send=None``: report only."""
    remind = timedelta(hours=settings.alert_remind_hours)
    out = []
    for c in evaluate(session, settings, now):
        last = _latest(session, c.key)
        state = _action(c, last, now, remind)
        row: dict[str, Any] = {"key": c.key, "firing": c.firing, "action": state}
        if state is not None:
            text = _text(c, state, now, settings.pick_tz)
            row["message"] = text
            if send is not None:
                delivered, error = send(text)
                session.add(
                    AlertEvent(
                        key=c.key,
                        state=state,
                        message=text[:2000],
                        detail=c.detail,
                        channel=channel,
                        delivered=delivered,
                        error=redact(error, 500) or None,
                    )
                )
                session.flush()
                row["delivered"] = delivered
        out.append(row)
    return out
