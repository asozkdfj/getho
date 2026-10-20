"""`edge verify-leagues` - score more leagues with the "verified" rule (research).

Selection, fixed 2026-10-20 before any league was scored: the divisions of the
Club Football Match Data file (football-data.co.uk results, the file the shots
experiment uses) whose three test seasons 2023-24, 2024-25 and 2025-26 each
hold at least 90% of the division's usual season. That gives the 11 leagues in
EXTRA_LEAGUES. Left out: National League (2024-25 incomplete), Greek Super
League (seasons missing), and the calendar-year leagues of the file (their data
stops in early 2025).

Same rule as the 10 verified leagues (backtest_cli.league_summary, ADR-013):
walk-forward production model, warm-up 2018-19..2022-23, test from 2023-24,
verified = at least 300 test matches AND the 95% CI of its log-loss gain over the
base rate above 0. The de-margined Bet365 market on the same test matches is
reported for context (not part of the rule).

This writes a separate report. It does not change which leagues the service
treats as verified (that comes from the imported production backtest report);
applying it widens the Today's Pick candidates, so it needs Codex QA and the
user's approval first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from edge_ingestion.backtest_cli import MIN_VERIFIED_TEST_MATCHES, league_summary
from edge_ingestion.feature_experiment import metrics
from edge_ingestion.history import club_match_data
from edge_ml.backtest import BacktestConfig, evaluate, walk_forward
from edge_ml.forecasters import BaseRateForecaster, EloOnlyForecaster, ModelForecaster
from edge_ml.market import devig
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams

logger = logging.getLogger(__name__)

FIRST, LAST, TEST_FROM = "2018-19", "2025-26", "2023-24"


@dataclass(frozen=True, slots=True)
class ExtraLeague:
    code: str
    division: str  # football-data.co.uk code in the Club Football Match Data file
    name: str
    country: str
    api_football_id: str  # to be confirmed against the server's leagues table


EXTRA_LEAGUES: dict[str, ExtraLeague] = {
    lg.code: lg
    for lg in (
        ExtraLeague("en.3", "E2", "League One", "England", "41"),
        ExtraLeague("en.4", "E3", "League Two", "England", "42"),
        ExtraLeague("es.2", "SP2", "Segunda División", "Spain", "141"),
        ExtraLeague("it.2", "I2", "Serie B", "Italy", "136"),
        ExtraLeague("fr.2", "F2", "Ligue 2", "France", "62"),
        ExtraLeague("tr.1", "T1", "Süper Lig", "Turkey", "203"),
        ExtraLeague("be.1", "B1", "Jupiler Pro League", "Belgium", "144"),
        ExtraLeague("sc.1", "SC0", "Premiership", "Scotland", "179"),
        ExtraLeague("sc.2", "SC1", "Championship", "Scotland", "180"),
        ExtraLeague("sc.3", "SC2", "League One", "Scotland", "183"),
        ExtraLeague("sc.4", "SC3", "League Two", "Scotland", "184"),
    )
}


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default=",".join(EXTRA_LEAGUES), help="codes, comma-separated")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")


def load(lg: ExtraLeague, cache_dir: Path) -> tuple[list[Any], dict[str, int]]:
    text = club_match_data.fetch(cache_dir).read_text(encoding="utf-8")
    matches = [
        m
        for m in club_match_data.parse(text, lg.division)
        if FIRST <= (m.result.season or "") <= LAST
    ]
    counts: dict[str, int] = defaultdict(int)
    for m in matches:
        counts[m.result.season or ""] += 1
    return matches, dict(sorted(counts.items()))


def score_league(lg: ExtraLeague, cache_dir: Path) -> dict[str, Any]:
    matches, counts = load(lg, cache_dir)
    test_start = min(m.result.kickoff_at for m in matches if m.result.season == TEST_FROM)
    cfg = BacktestConfig(eval_start=test_start, reference="production")
    preds = walk_forward(
        matches,
        [BaseRateForecaster(), EloOnlyForecaster(), ModelForecaster("production", ModelParams())],
        cfg,
    )
    summary = league_summary(lg.code, evaluate(preds, cfg), len(matches))
    summary.update(
        name=lg.name,
        country=lg.country,
        division=lg.division,
        provider_ids={"api_football": lg.api_football_id},
        matches_per_season=counts,
    )
    # context: the de-margined Bet365 market on the same test matches
    idx = np.array([k for k, m in enumerate(preds.matches) if m.odds is not None], dtype=int)
    if len(idx):
        market = np.asarray([devig(preds.matches[k].odds) for k in idx], dtype=float)
        y = np.asarray(preds.outcomes)[idx]
        prod = np.asarray(preds.probs["production"]).reshape(-1, 3)[idx]
        summary["market_context"] = {
            "n_matches": len(idx),
            "market": metrics(market.reshape(-1, 3), y),
            "production": metrics(prod, y),
        }
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    leagues = []
    for code in codes:
        s = score_league(EXTRA_LEAGUES[code], args.cache_dir)
        logger.info(
            "%s %s: test n=%d gain %.4f [%.4f, %.4f] verified=%s",
            code,
            s["name"],
            s["test_matches"],
            s["gain_vs_base_rate"]["mean"],
            s["gain_vs_base_rate"]["ci_low"],
            s["gain_vs_base_rate"]["ci_high"],
            s["verified"],
        )
        leagues.append(s)
    path = club_match_data.fetch(args.cache_dir)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "league_verification_europe_v1",
        "protocol": __doc__,
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "rule": {
            "min_test_matches": MIN_VERIFIED_TEST_MATCHES,
            "test_from": TEST_FROM,
            "verified_if": "test_matches >= min AND gain_vs_base_rate.ci_low > 0",
        },
        "source": {
            "url": club_match_data.URL,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "applied_to_service": False,
        "leagues": leagues,
    }
    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return report


def summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for s in report["leagues"]:
        g = s["gain_vs_base_rate"]
        m = s.get("market_context") or {}
        out.append(
            {
                "code": s["code"],
                "league": f"{s['country']} - {s['name']}",
                "test_matches": s["test_matches"],
                "gain_vs_base_rate": [
                    round(g["mean"], 4),
                    round(g["ci_low"], 4),
                    round(g["ci_high"], 4),
                ],
                "verified": s["verified"],
                "production_ll": round(s["models"]["production"]["log_loss"], 4),
                "market_ll": round(m["market"]["log_loss"], 4) if m else None,
            }
        )
    return out
