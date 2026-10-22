"""`edge check-alerts` - send collection alerts to Telegram (docs/SERVER.md, 알림).

Run by host cron every 10 minutes (`infra/server/alerts.sh --install-cron`), so
it still runs when the worker is stuck. The bot token and chat id come from
.env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID); without them it only reports.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from edge_api.config import Settings
from edge_api.services.alerts import PREFIX, Sender, check, redact

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"

# (url, form body, timeout) -> HTTP status; injectable for tests
Transport = Callable[[str, bytes, float], int]


def _urllib_post(url: str, body: bytes, timeout: float) -> int:
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status)


def telegram_sender(settings: Settings, transport: Transport = _urllib_post) -> Sender | None:
    if settings.telegram_bot_token is None or not settings.telegram_chat_id:
        return None
    token = settings.telegram_bot_token.get_secret_value()
    url = TELEGRAM_URL.format(token=token)
    chat = settings.telegram_chat_id

    def send(text: str) -> tuple[bool, str | None]:
        body = urllib.parse.urlencode(
            {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
        ).encode()
        try:
            status = transport(url, body, 10.0)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # never let the token reach the log or the database
            return False, redact(f"{type(exc).__name__}: {exc}".replace(token, "***"), 500)
        return (True, None) if 200 <= status < 300 else (False, f"HTTP {status}")

    return send


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dry-run", action="store_true", help="report only, send and record nothing")
    p.add_argument("--test", action="store_true", help="send one test message and stop")


def run(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    from edge_api.db.session import session_scope
    from edge_api.timeutil import utcnow

    send = telegram_sender(settings)
    if args.test:
        if send is None:
            return {"configured": False, "note": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"}
        delivered, error = send(f"{PREFIX} 알림 테스트 메시지예요. 이 메시지가 보이면 설정 완료.")
        return {"configured": True, "delivered": delivered, "error": error}
    with session_scope() as session:
        checks = check(session, settings, utcnow(), None if args.dry_run else send)
    return {
        "configured": send is not None,
        "dry_run": args.dry_run or send is None,
        "checks": checks,
    }


def print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
