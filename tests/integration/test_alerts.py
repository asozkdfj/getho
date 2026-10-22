"""Collection alerts: checks, state changes, delivery retries, Telegram sender."""

import urllib.error
from dataclasses import asdict
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.config import Settings
from edge_api.db.models import AlertEvent, DailyPick, IngestionRun
from edge_api.services.alerts import check, evaluate, redact
from edge_ingestion.alerts import telegram_sender

SETTINGS = Settings(data_provider="mock")


class Outbox:
    def __init__(self, ok=True):
        self.sent: list[str] = []
        self.ok = ok

    def __call__(self, text_):
        self.sent.append(text_)
        return (True, None) if self.ok else (False, "HTTP 502")


def _run(s, status, at, error=None):
    s.add(IngestionRun(provider="mock", started_at=at, finished_at=at, status=status, error=error))
    s.flush()


def _states(s, key):
    return [
        (e.state, e.delivered)
        for e in s.scalars(select(AlertEvent).where(AlertEvent.key == key).order_by(AlertEvent.id))
    ]


def _by_key(rows):
    return {r["key"]: r for r in rows}


def test_failing_streak_fires_once_reminds_and_resolves(session_factory, seeded, now):
    from conftest import set_test_wall_clock

    out = Outbox()
    with session_factory() as s:
        assert not _by_key(check(s, SETTINGS, now, out))["pipeline_failing"]["firing"]
        _run(s, "failed", now + timedelta(minutes=30), "ProviderError: quota key=" + "a" * 40)
        assert (
            _by_key(check(s, SETTINGS, now + timedelta(minutes=31), out))["pipeline_failing"][
                "action"
            ]
            is None
        )  # one failure is not a streak
        _run(s, "failed", now + timedelta(minutes=60))
        first = _by_key(check(s, SETTINGS, now + timedelta(minutes=61), out))["pipeline_failing"]
        assert first["action"] == "firing" and first["delivered"] is True
        assert "2회 연속 실패" in first["message"]
        sent = len(out.sent)
        # still failing, no change: nothing new
        assert (
            _by_key(check(s, SETTINGS, now + timedelta(minutes=71), out))["pipeline_failing"][
                "action"
            ]
            is None
        )
        assert len(out.sent) == sent
        # a reminder after alert_remind_hours
        later = now + timedelta(hours=13)
        set_test_wall_clock(s, later)
        assert _by_key(check(s, SETTINGS, later, out))["pipeline_failing"]["action"] == "firing"
        _run(s, "success", later + timedelta(minutes=5))
        done = _by_key(check(s, SETTINGS, later + timedelta(minutes=6), out))
        assert done["pipeline_failing"]["action"] == "resolved"
        assert "해결" in done["pipeline_failing"]["message"]
        assert _states(s, "pipeline_failing") == [
            ("firing", True),
            ("firing", True),
            ("resolved", True),
        ]


def test_error_text_is_redacted(session_factory, seeded, now):
    out = Outbox()
    with session_factory() as s:
        secret = "x" * 32
        _run(s, "failed", now + timedelta(minutes=30), f"ProviderError: bad key {secret}")
        _run(s, "failed", now + timedelta(minutes=60), f"ProviderError: bad key {secret}")
        row = _by_key(check(s, SETTINGS, now + timedelta(minutes=61), out))["pipeline_failing"]
    assert secret not in row["message"] and "***" in row["message"]
    assert redact("a" * 400) == "***"  # one long token
    assert redact("ab " * 200).endswith("…") and len(redact("ab " * 200)) == 300


def test_stale_and_never_succeeded(session_factory, seeded, now):
    with session_factory() as s:
        fresh = _by_key([asdict(c) for c in evaluate(s, SETTINGS, now + timedelta(hours=1))])
        assert fresh["pipeline_stale"]["firing"] is False
        stale = _by_key([asdict(c) for c in evaluate(s, SETTINGS, now + timedelta(hours=9))])
        assert stale["pipeline_stale"]["firing"] is True
        assert "8시간" in stale["pipeline_stale"]["message"]
    with session_factory() as s:  # empty database: never a successful run
        s.execute(text("TRUNCATE ingestion_runs"))
        none = _by_key([asdict(c) for c in evaluate(s, SETTINGS, now)])
        assert none["pipeline_stale"]["firing"] is True
        assert "없어요" in none["pipeline_stale"]["message"]
        s.rollback()


def test_pick_missing_after_the_grace_period(session_factory, seeded, now):
    # the next pick day starts at 09:00 KST = 00:00 UTC on the 16th
    next_publish = now.replace(hour=0) + timedelta(days=1)
    with session_factory() as s:
        # no pick decided yet for the 16th (the seed only covers the 15th, if any)
        assert not s.scalars(
            select(DailyPick).where(DailyPick.pick_date == next_publish.date())
        ).all()
        early = _by_key(
            [asdict(c) for c in evaluate(s, SETTINGS, next_publish + timedelta(minutes=60))]
        )
        assert early["pick_missing"]["firing"] is False  # within the 90-minute grace
        late = _by_key(
            [asdict(c) for c in evaluate(s, SETTINGS, next_publish + timedelta(minutes=91))]
        )
        assert late["pick_missing"]["firing"] is True
        assert late["pick_missing"]["detail"] == {"pick_date": "2026-10-16"}


def test_undelivered_message_is_retried(session_factory, seeded, now):
    down, up = Outbox(ok=False), Outbox()
    with session_factory() as s:
        _run(s, "failed", now + timedelta(minutes=30))
        _run(s, "failed", now + timedelta(minutes=60))
        check(s, SETTINGS, now + timedelta(minutes=61), down)
        check(s, SETTINGS, now + timedelta(minutes=71), up)
        check(s, SETTINGS, now + timedelta(minutes=81), up)
        assert _states(s, "pipeline_failing") == [("firing", False), ("firing", True)]
        assert sum("연속 실패" in m for m in up.sent) == 1
        event = s.scalars(
            select(AlertEvent).where(AlertEvent.key == "pipeline_failing").order_by(AlertEvent.id)
        ).first()
        assert event.error == "HTTP 502"


def test_dry_run_records_nothing(session_factory, seeded, now):
    with session_factory() as s:
        _run(s, "failed", now + timedelta(minutes=30))
        _run(s, "failed", now + timedelta(minutes=60))
        rows = _by_key(check(s, SETTINGS, now + timedelta(minutes=61), None))
        assert rows["pipeline_failing"]["action"] == "firing"
        assert "delivered" not in rows["pipeline_failing"]
        assert s.scalar(select(func.count()).select_from(AlertEvent)) == 0


def test_alert_events_are_append_only(session_factory, seeded, now):
    with session_factory() as s:
        _run(s, "failed", now + timedelta(minutes=30))
        _run(s, "failed", now + timedelta(minutes=60))
        check(s, SETTINGS, now + timedelta(minutes=61), Outbox())
        s.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM alert_events"))
        s.rollback()


def test_telegram_sender_posts_and_never_leaks_the_token():
    assert telegram_sender(Settings(data_provider="mock")) is None
    token = "123456:" + "T" * 35
    calls = []

    def ok(url, body, timeout):
        calls.append((url, body, timeout))
        return 200

    settings = Settings(data_provider="mock", telegram_bot_token=token, telegram_chat_id="42")
    assert telegram_sender(settings, ok)("안녕") == (True, None)
    url, body, _ = calls[0]
    assert url == f"https://api.telegram.org/bot{token}/sendMessage"
    assert b"chat_id=42" in body and "안녕".encode() not in body  # form-encoded
    assert token not in repr(settings)

    def fails(url, body, timeout):
        raise urllib.error.URLError(f"cannot reach {url}")

    delivered, error = telegram_sender(settings, fails)("x")
    assert delivered is False and token not in error and "T" * 30 not in error
    assert telegram_sender(settings, lambda *a: 401)("x") == (False, "HTTP 401")
