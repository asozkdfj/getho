"""`edge betman-*` commands: load Betman prices, map events, show their state.

    edge betman-import --file round.csv [--assume-tz Asia/Seoul] [--observed-now]
    edge betman-import --file - --format json < round.json      # stdin (server)
    edge betman-status [--round 2026-81] [--at 2026-10-24T09:00:00+09:00]
    edge betman-map --product proto --round 2026-81 --event 12 --fixture 4567 --learn-aliases
    edge betman-map --product proto --round 2026-81 --event 12 --reject "not in our leagues"
    edge betman-rules

Research only (docs/betman/README.md): nothing is bought or recommended.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from edge_api.betman_rules import RULES, RULES_VERSION
from edge_api.config import get_settings
from edge_api.db.session import session_scope
from edge_api.services import betman
from edge_api.timeutil import ensure_utc, utcnow
from edge_ingestion.betman import BetmanImportError, parse, store

COMMANDS = ("betman-import", "betman-status", "betman-map", "betman-rules")


def add_arguments(sub: Any) -> None:
    imp = sub.add_parser("betman-import", help="load Betman 1X2 prices (CSV/JSON; research)")
    imp.add_argument("--file", required=True, help="path, or - for stdin")
    imp.add_argument("--format", choices=("csv", "json"), help="default: from the file name")
    imp.add_argument(
        "--source-mode",
        choices=("file", "manual"),
        default="file",
        help="manual = typed by a person, file = exported file",
    )
    imp.add_argument("--assume-tz", help="IANA zone for times without an offset, e.g. Asia/Seoul")
    imp.add_argument(
        "--observed-now",
        action="store_true",
        help="the prices were seen on Betman just now (observed_at = load time)",
    )
    st = sub.add_parser("betman-status", help="Betman events: mapping and purchasable prices")
    st.add_argument("--product")
    st.add_argument("--round")
    st.add_argument("--at", help="ISO-8601 time (default: now)")
    mp = sub.add_parser("betman-map", help="link a Betman event to a fixture, or reject it")
    mp.add_argument("--product", required=True)
    mp.add_argument("--round", required=True)
    mp.add_argument("--event", type=int, required=True)
    what = mp.add_mutually_exclusive_group(required=True)
    what.add_argument("--fixture", type=int, help="fixture id (see betman-status suggestions)")
    what.add_argument("--reject", help="reason this event has no fixture here")
    mp.add_argument(
        "--learn-aliases",
        action="store_true",
        help="remember the Betman league/team names for automatic mapping",
    )
    sub.add_parser("betman-rules", help="Betman rules: confirmed and unverified")


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def run(args: argparse.Namespace) -> int:
    provider = get_settings().data_provider
    if args.command == "betman-rules":
        _print({"version": RULES_VERSION, "rules": [asdict(r) for r in RULES]})
        return 0

    if args.command == "betman-import":
        if args.file == "-":
            if not args.format:
                print("--format is required with --file -", file=sys.stderr)
                return 2
            data, name = sys.stdin.buffer.read(), None
        else:
            path = Path(args.file)
            data, name = path.read_bytes(), path.name
        fmt = args.format or ("json" if name and name.lower().endswith(".json") else "csv")
        now = utcnow()
        try:
            rows = parse(
                data.decode("utf-8-sig"),
                fmt,
                now=now,
                assume_tz=args.assume_tz,
                observed_now=args.observed_now,
            )
        except (BetmanImportError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors = exc.errors if isinstance(exc, BetmanImportError) else [str(exc)]
            _print({"command": args.command, "stored": False, "errors": errors})
            return 2
        with session_scope() as session:
            result = store(
                session, provider, data, rows, source_mode=args.source_mode, filename=name
            )
        _print({"command": args.command, "stored": not result.already_loaded, **asdict(result)})
        return 0

    if args.command == "betman-status":
        at = (
            ensure_utc(datetime.fromisoformat(args.at.replace("Z", "+00:00")))
            if args.at
            else utcnow()
        )
        with session_scope() as session:
            _print(betman.status_report(session, at, product=args.product, round_id=args.round))
        return 0

    key = betman.EventKey(args.product, args.round, args.event)
    with session_scope() as session:
        if args.reject:
            m = betman.manual_reject(session, key, args.reject)
        else:
            info = betman.event_info(session, key)
            if info is None:
                print(f"no prices stored for {key}", file=sys.stderr)
                return 2
            try:
                m = betman.manual_map(
                    session, provider, info, args.fixture, learn_aliases=args.learn_aliases
                )
            except betman.MappingError as exc:
                _print({"command": args.command, "mapped": False, "error": str(exc)})
                return 2
        _print(
            {
                "command": args.command,
                "event": asdict(key),
                "status": m.status,
                "fixture_id": m.fixture_id,
                "reason": m.reason,
            }
        )
    return 0
