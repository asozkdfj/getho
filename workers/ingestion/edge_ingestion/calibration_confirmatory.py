"""`edge score-calibration-confirmatory` - the one-time scoring of the
pre-registered confirmatory test of the frozen top-outcome calibration.

Protocol: docs/experiments/calibration-confirmatory-2026-27.md (committed before
any 2026-27 result was scored; this code adds nothing to it and changes nothing
in it). Summary of what the code implements:

Map       TopOutcomeCalibrator("logistic") with the frozen a, b below (from
          ml/reports/backtest-calibration.json "frozen_map_for_confirmation").
          Never refitted.
Model     The production model as in the exploratory experiment (weekly refit,
          results enter training 3 h after kickoff), trained on the same
          division's results from 2018-19 on; probabilities only for the target
          season.
Data      football-data.co.uk season CSVs (downloaded, cached; SHA-256, row and
          no-result counts per file in the report), 9 leagues.
Scope     League matches kicking off 2026-10-19 00:00 UTC .. 2027-06-30 (end of
          day, UTC). Matches without a result are left out and counted.
When      Once, after every league's season is complete. Until then the command
          reports only counts and completeness - no metric of any kind - so
          running it early cannot leak an interim result.
Decision  "undecidable" below 2,500 matches. Standard gate (validation gain
          >= 0.001, confirmation gain >= 0.002, weekly paired CI upper < 0):
          the exploratory validation gain (+0.00048) already fails it, the two
          confirmation numbers are still reported. Calibration criteria C1-C3
          as in the protocol. Reference tables decide nothing.

`--season` other than 2026-27 runs a REHEARSAL on a past, complete season (the
same code end to end, whole season, labelled as such): the frozen map was fitted
on those seasons, so a rehearsal checks the plumbing, not the hypothesis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

import edge_ml
from edge_ingestion.calibration_backtest import (
    _git_commit,
    bands,
    breakdown,
    brier,
    daily_top3,
    log_loss,
    tier_gap,
    top_index,
)
from edge_ingestion.feature_experiment import production_rows
from edge_ingestion.history import football_data
from edge_ingestion.history.club_match_data import DIVISIONS, team_key
from edge_ml.calibration import TopOutcomeCalibrator
from edge_ml.metrics import cluster_bootstrap_ci
from edge_ml.model import MODEL_VERSION, ModelParams

logger = logging.getLogger(__name__)

PROTOCOL = "docs/experiments/calibration-confirmatory-2026-27.md"
SEASON = "2026-27"
START = datetime(2026, 10, 19, tzinfo=UTC)
END = datetime(2027, 7, 1, tzinfo=UTC)  # exclusive: through 2027-06-30
FAR_FUTURE = datetime(3000, 1, 1, tzinfo=UTC)
FIRST = "2018-19"  # history the production model trains on
LEAGUES = ("de.1", "de.2", "en.1", "en.2", "es.1", "fr.1", "it.1", "nl.1", "pt.1")
FROZEN_A, FROZEN_B = 0.016148045028258628, 1.1675089558170335
FROZEN_MODEL_VERSION = "0.2.0"
EXPLORATORY_VALIDATION_GAIN = 0.0004833428733239664  # backtest-calibration.json
MIN_MATCHES = 2500
TIER = 0.60
C2_MAX_GAP = 0.015
C3_MAX_GROWTH = 0.005
STANDARD_GATE = {"validation_gain": 0.001, "confirmation_gain": 0.002, "ci_upper_below": 0.0}


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--season", default=SEASON, help="2026-27 scores; a past season rehearses")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the full JSON report here")


def frozen_calibrator() -> TopOutcomeCalibrator:
    cal = TopOutcomeCalibrator("logistic")
    cal.params = (FROZEN_A, FROZEN_B)
    return cal


def seasons_from(first: str, last: str) -> list[str]:
    start, end = int(first[:4]), int(last[:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start, end + 1)]


def season_complete(rows_in_season: list[tuple[str, str]]) -> dict[str, Any]:
    """A double round robin is complete when n teams played n (n - 1) matches."""
    teams = {t for pair in rows_in_season for t in pair}
    expected = len(teams) * (len(teams) - 1)
    return {
        "teams": len(teams),
        "played": len(rows_in_season),
        "expected": expected,
        "complete": bool(teams) and len(rows_in_season) >= expected,
    }


def protocol_sha256() -> str | None:
    path = Path(edge_ml.__file__).resolve().parents[2] / PROTOCOL
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def collect(season: str, cache_dir: Path) -> tuple[list[Any], dict[str, Any]]:
    """Production rows for the target season and a per-league data record."""
    params = ModelParams()
    rows: list[Any] = []
    data: dict[str, Any] = {}
    for code in LEAGUES:
        matches, files = football_data.load_seasons(
            DIVISIONS[code], seasons_from(FIRST, season), cache_dir, key=team_key
        )
        target = [m for m in matches if m.result.season == season]
        history = sum(1 for m in matches if m.result.season == FIRST)
        data[code] = {
            "files": [
                {
                    "season": f.season,
                    "sha256": f.sha256,
                    "rows": f.rows,
                    "played": f.played,
                    "no_result": f.no_result,
                }
                for f in files
            ],
            "completeness": season_complete([(m.result.home, m.result.away) for m in target]),
        }
        if target:
            rows += production_rows(code, matches, params, history, [season])
    return rows, data


def score(
    rows: list[Any], window: tuple[datetime, datetime]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Metrics and decision for the rows inside the window."""
    lo, hi = window
    rows = [r for r in rows if lo <= r.match.result.kickoff_at < hi]
    probs = np.array([r.production for r in rows], dtype=float).reshape(-1, 3)
    y = np.array([r.match.outcome_index for r in rows], dtype=int)
    cal = frozen_calibrator().calibrate_matrix(probs) if len(rows) else probs
    everything = np.ones(len(rows), dtype=bool)
    n = len(rows)
    if n == 0:
        return {"n_matches": 0}, {"conclusion": "undecidable", "reason": "no matches"}

    ll_p, ll_c = log_loss(probs, y), log_loss(cal, y)
    weeks = [r.match.result.kickoff_at.isocalendar()[:2] for r in rows]
    ci_lo, ci_hi = cluster_bootstrap_ci(ll_c - ll_p, weeks)
    ref_top = probs[np.arange(n), top_index(probs)]
    strong, rest = ref_top >= TIER, ref_top < TIER

    log_loss_gain = float(ll_p.mean() - ll_c.mean())
    brier_gain = float(brier(probs, y).mean() - brier(cal, y).mean())
    gaps = {
        "strong_n": int(strong.sum()),
        "strong_gap_production": tier_gap(probs, y, strong) if strong.any() else None,
        "strong_gap_calibrated": tier_gap(cal, y, strong) if strong.any() else None,
        "rest_n": int(rest.sum()),
        "rest_gap_production": tier_gap(probs, y, rest) if rest.any() else None,
        "rest_gap_calibrated": tier_gap(cal, y, rest) if rest.any() else None,
    }
    c1 = log_loss_gain >= 0 and brier_gain >= 0
    c2 = (
        gaps["strong_gap_calibrated"] is not None
        and gaps["strong_gap_calibrated"] <= C2_MAX_GAP
        and gaps["strong_gap_calibrated"] < gaps["strong_gap_production"]
    )
    c3 = (
        gaps["rest_gap_calibrated"] is None
        or gaps["rest_gap_calibrated"] <= gaps["rest_gap_production"] + C3_MAX_GROWTH
    )
    standard = {
        "validation_gain_exploratory": EXPLORATORY_VALIDATION_GAIN,
        "confirmation_gain": log_loss_gain,
        "confirmation_ci95_weekly": [ci_lo, ci_hi],
        "checks": {
            "validation_gain>=0.001": STANDARD_GATE["validation_gain"]
            <= EXPLORATORY_VALIDATION_GAIN,
            "confirmation_gain>=0.002": log_loss_gain >= STANDARD_GATE["confirmation_gain"],
            "ci_upper<0": ci_hi < STANDARD_GATE["ci_upper_below"],
        },
    }
    standard["passed"] = all(standard["checks"].values())
    calibration = {
        "c1_log_loss_gain": log_loss_gain,
        "c1_brier_gain": brier_gain,
        **gaps,
        "checks": {"C1": c1, "C2": bool(c2), "C3": bool(c3)},
    }
    calibration["passed"] = all(calibration["checks"].values())
    decision = {
        "n_matches": n,
        "conclusion": "undecidable" if n < MIN_MATCHES else "scored",
        "standard_gate": standard,
        "calibration_criteria": calibration,
        "deployed": False,
        "next": "service use needs Codex QA and the user's approval (protocol, TODO #38)",
    }

    def crossing(p: np.ndarray) -> dict[str, float]:
        top = p[np.arange(n), top_index(p)]
        return {
            "share_ge_55": float((top >= 0.55).mean()),
            "share_ge_65": float((top >= 0.65).mean()),
        }

    leagues = np.array([r.league for r in rows])
    months = np.array([r.match.result.kickoff_at.strftime("%Y-%m") for r in rows])
    as_dicts = [{"kickoff_at": r.match.result.kickoff_at.isoformat()} for r in rows]
    metrics = {
        "n_matches": n,
        "production": {"log_loss": float(ll_p.mean()), "brier": float(brier(probs, y).mean())},
        "calibrated": {"log_loss": float(ll_c.mean()), "brier": float(brier(cal, y).mean())},
        "reference_only": {
            "by_league": breakdown(leagues, probs, cal, y, everything),
            "by_month": breakdown(months, probs, cal, y, everything),
            "bands": {
                "production": bands(probs, y, probs, everything),
                "calibrated": bands(cal, y, probs, everything),
            },
            "tier_shares": {"production": crossing(probs), "calibrated": crossing(cal)},
            "daily_top3": {
                "production": daily_top3(as_dicts, probs, y, everything),
                "calibrated": daily_top3(as_dicts, cal, y, everything),
            },
        },
    }
    return metrics, decision


def run(args: argparse.Namespace) -> dict[str, Any]:
    confirmatory = args.season == SEASON
    rows, data = collect(args.season, args.cache_dir)
    complete = all(d["completeness"]["complete"] for d in data.values())
    report: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "top_outcome_calibration_confirmatory_2026_27",
        "mode": "confirmatory" if confirmatory else "rehearsal",
        "protocol": {"path": PROTOCOL, "sha256": protocol_sha256()},
        "code_commit": _git_commit(),
        "model_version": MODEL_VERSION,
        "frozen_model_version": FROZEN_MODEL_VERSION,
        "frozen_map": {"method": "logistic", "a": FROZEN_A, "b": FROZEN_B},
        "season": args.season,
        "window": [START.isoformat(), END.isoformat()] if confirmatory else "whole season",
        "source": {"url": football_data.SEASON_URL, "attribution": "football-data.co.uk"},
        "data": data,
        "all_seasons_complete": complete,
    }
    if MODEL_VERSION != FROZEN_MODEL_VERSION:
        report["status"] = "blocked"
        report["reason"] = (
            f"production model is {MODEL_VERSION}, the protocol froze {FROZEN_MODEL_VERSION}; "
            "score with the frozen model's code (check out its commit)"
        )
        return report
    if not complete:
        # No metric before the end: the protocol scores once.
        report["status"] = "not_scored"
        report["reason"] = "season not complete in every league; the protocol scores once"
        report["matches_so_far"] = len(rows)
        return report
    window = (START, END) if confirmatory else (datetime(1900, 1, 1, tzinfo=UTC), FAR_FUTURE)
    metrics, decision = score(rows, window)
    report["status"] = "scored" if confirmatory else "rehearsal_scored"
    report["metrics"] = metrics
    report["decision"] = decision
    return report


def summary(report: dict[str, Any]) -> dict[str, Any]:
    out = {k: report.get(k) for k in ("mode", "status", "reason", "season", "all_seasons_complete")}
    out["completeness"] = {code: d["completeness"] for code, d in report.get("data", {}).items()}
    if "decision" in report:
        out["decision"] = report["decision"]
        out["log_loss"] = {
            "production": report["metrics"]["production"]["log_loss"],
            "calibrated": report["metrics"]["calibrated"]["log_loss"],
        }
    return out


def write(report: dict[str, Any], path: Path | None) -> None:
    if path:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
