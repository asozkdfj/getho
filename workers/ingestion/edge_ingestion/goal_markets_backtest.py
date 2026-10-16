"""`edge backtest-goal-markets` - over/under 2.5 and Asian handicap from the model.

Pre-registered protocol (committed before the first run; do not edit after results):

Question  Can the service show over/under 2.5 and Asian handicap probabilities
          derived from its production model as its own analysis, the way it
          shows 1X2? The model is NOT changed or refitted for these markets.
Data      Club Football Match Data (football-data.co.uk results + Bet365 odds,
          MIT copy), 2018-19..2025-26, file SHA-256 in the report; the same 9
          leagues as the market baseline, pooled: en.1 en.2 de.1 de.2 es.1 it.1
          fr.1 nl.1 pt.1. Prices: Bet365 Over25/Under25 and the Asian handicap
          line (HandiSize, home team's line) with HandiHome/HandiAway. The copy
          rounds quarter lines to one decimal (-0.3 = -0.25, -0.8 = -0.75); they
          are mapped back, other unexpected lines are dropped. Capture time of
          the odds is undocumented (pre-match, maybe later than 09:00 KST).
Timing    Production expected goals from the shared walk-forward engine: refit
          weekly, results enter training 3 h after kickoff, refit grid
          restarting at the warm-up (2019-20), validation (2020-21..2022-23)
          and follow-up (2023-24..2025-26) starts.
Model     The production score matrix from those expected goals (independent
          Poisson, the production rho and max goals). Over 2.5 = P(total >= 3).
          Handicap at Bet365's line: home probability A / (A + B), A and B the
          expected share of the stake won and lost (quarter lines split the
          stake, whole lines can push).
Market    Bet365's two prices with the margin removed proportionally.
Naive     Over/under: the league's share of over-2.5 matches among results
          known at the refit time (all loaded seasons). Handicap: 0.5 (the
          bookmaker sets the line to split the action).
Scores    Weighted log loss and Brier: each match counts by the share of the
          stake that was settled (full result 1, half win/loss 0.5, push 0), so
          A / (A + B) is the proper target. Weekly cluster-bootstrap 95% CI of
          paired differences (per-match contributions scaled by n / sum of
          weights). Each market uses its own common sample (all three
          forecasts known).
Decision  Per market, the model probability may be offered for display
          (still a product decision, nothing is deployed automatically) only if
          D1 informative: model beats naive in validation AND in follow-up with
             a follow-up gain >= 0.002 and weekly CI upper bound < 0, and
          D2 calibrated (follow-up): |mean predicted - observed| <= 0.02 and
             ECE (10 bins) <= 0.03.
          Model vs market is measured and reported, not a criterion (the 1X2
          market was already more accurate than the model; that is disclosed).
Descriptive (no decision): per-league follow-up; handicap half lines only
          (no pushes); predicted vs observed mean total goals; flagged prices
          (model - market >= t and model expected profit >= t, t in 0.03, 0.05,
          0.10), 1 unit each, realised return with weekly CI. The product never
          places bets.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from edge_ingestion.feature_experiment import RESULT_DELAY, Row, production_rows
from edge_ingestion.history import club_match_data
from edge_ingestion.history.club_match_data import GoalMarketOdds, match_key
from edge_ml.goal_markets import (
    handicap_shares,
    over_probability,
    profit,
    settle,
    two_way_devig,
)
from edge_ml.metrics import cluster_bootstrap_ci
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams
from edge_ml.poisson import score_matrix

logger = logging.getLogger(__name__)

FIRST, LAST = "2018-19", "2025-26"
WARMUP = ["2019-20"]
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25", "2025-26"]
LEAGUES = "en.1,en.2,de.1,de.2,es.1,it.1,fr.1,nl.1,pt.1"
MIN_GAIN_FOLLOW_UP = 0.002
MAX_MEAN_GAP = 0.02
MAX_ECE = 0.03
FLAG_THRESHOLDS = (0.03, 0.05, 0.10)
EPS = 1e-12


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default=LEAGUES, help="pooled for the decision")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")


@dataclass(slots=True)
class Sample:
    """One market's common sample: per match the settled shares of side A
    (over / home) and side B, and the three forecasts of side A."""

    market: str
    rows: list[Row]
    won: np.ndarray  # share of a side-A bet won
    lost: np.ndarray  # share of a side-A bet lost
    model: np.ndarray
    market_p: np.ndarray
    naive: np.ndarray
    model_won: np.ndarray  # expected shares under the model (for flags)
    model_lost: np.ndarray
    price_a: np.ndarray
    price_b: np.ndarray
    line: np.ndarray

    def mask(self, seasons: list[str], league: str | None = None) -> np.ndarray:
        m = np.array([r.match.result.season in seasons for r in self.rows], dtype=bool)
        if league is not None:
            m &= np.array([r.league == league for r in self.rows], dtype=bool)
        return m


# ------------------------------------------------------------------ scoring
def weighted_log_loss(p: np.ndarray, won: np.ndarray, lost: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return -(won * np.log(p) + lost * np.log(1 - p))


def weighted_brier(p: np.ndarray, won: np.ndarray, lost: np.ndarray) -> np.ndarray:
    return won * (1 - p) ** 2 + lost * p**2


def calibration(p: np.ndarray, won: np.ndarray, lost: np.ndarray, bins: int = 10) -> dict:
    w = won + lost
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        sel = idx == b
        if w[sel].sum() > 0:
            ece += abs((w[sel] * p[sel]).sum() - won[sel].sum())
    total = w.sum()
    return {
        "mean_predicted": float((w * p).sum() / total),
        "observed": float(won.sum() / total),
        "ece": float(ece / total),
    }


def scores(s: Sample, p: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    won, lost = s.won[mask], s.lost[mask]
    total = (won + lost).sum()
    return {
        "log_loss": float(weighted_log_loss(p[mask], won, lost).sum() / total),
        "brier": float(weighted_brier(p[mask], won, lost).sum() / total),
        **calibration(p[mask], won, lost),
    }


def paired(s: Sample, cand: np.ndarray, base: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    """cand minus base; negative = cand is better."""
    won, lost = s.won[mask], s.lost[mask]
    scale = mask.sum() / (won + lost).sum()
    diff = (
        weighted_log_loss(cand[mask], won, lost) - weighted_log_loss(base[mask], won, lost)
    ) * scale
    weeks = [
        r.match.result.kickoff_at.isocalendar()[:2] for r, k in zip(s.rows, mask, strict=True) if k
    ]
    lo, hi = cluster_bootstrap_ci(diff, weeks)
    return {"log_loss_diff": float(diff.mean()), "ci95_weekly": [lo, hi], "weeks": len(set(weeks))}


def segment(s: Sample, mask: np.ndarray) -> dict[str, Any]:
    return {
        "n_matches": int(mask.sum()),
        "settled_weight": float((s.won[mask] + s.lost[mask]).sum()),
        "model": scores(s, s.model, mask),
        "market": scores(s, s.market_p, mask),
        "naive": scores(s, s.naive, mask),
        "model_vs_naive": paired(s, s.model, s.naive, mask),
        "market_vs_model": paired(s, s.market_p, s.model, mask),
    }


def decide(validation: dict[str, Any], follow_up: dict[str, Any]) -> dict[str, Any]:
    v_gain = validation["naive"]["log_loss"] - validation["model"]["log_loss"]
    fu = follow_up["model_vs_naive"]
    f_gain = -fu["log_loss_diff"]
    cal = follow_up["model"]
    d1 = v_gain > 0 and f_gain >= MIN_GAIN_FOLLOW_UP and fu["ci95_weekly"][1] < 0
    gap = abs(cal["mean_predicted"] - cal["observed"])
    d2 = gap <= MAX_MEAN_GAP and cal["ece"] <= MAX_ECE
    return {
        "d1_informative": {
            "validation_gain_vs_naive": v_gain,
            "follow_up_gain_vs_naive": f_gain,
            "follow_up_ci95_weekly": fu["ci95_weekly"],
            "passed": bool(d1),
        },
        "d2_calibrated": {"mean_gap": gap, "ece": cal["ece"], "passed": bool(d2)},
        "eligible_for_display": bool(d1 and d2),
    }


def flags(s: Sample, mask: np.ndarray) -> list[dict[str, Any]]:
    """Both sides: flag when model - market >= t and model expected profit >= t."""
    out = []
    idx = np.flatnonzero(mask)
    for t in FLAG_THRESHOLDS:
        returns, weeks = [], []
        for i in idx:
            week = s.rows[i].match.result.kickoff_at.isocalendar()[:2]
            sides = (
                (
                    s.model[i],
                    s.market_p[i],
                    s.model_won[i],
                    s.model_lost[i],
                    s.won[i],
                    s.lost[i],
                    s.price_a[i],
                ),
                (
                    1 - s.model[i],
                    1 - s.market_p[i],
                    s.model_lost[i],
                    s.model_won[i],
                    s.lost[i],
                    s.won[i],
                    s.price_b[i],
                ),
            )
            for p_model, p_market, exp_won, exp_lost, won, lost, price in sides:
                if p_model - p_market >= t and profit(exp_won, exp_lost, price) >= t:
                    returns.append(profit(won, lost, price))
                    weeks.append(week)
        values = np.asarray(returns)
        lo, hi = cluster_bootstrap_ci(values, weeks) if len(values) else (None, None)
        out.append(
            {
                "threshold": t,
                "flags": len(values),
                "mean_return": float(values.mean()) if len(values) else None,
                "mean_return_ci95_weekly": [lo, hi],
            }
        )
    return out


# ------------------------------------------------------------------ samples
def over_rate_lookup(matches: list[Any]) -> Any:
    """Share of over-2.5 results known (kickoff + delay) before a time."""
    known = sorted(
        (m.result.kickoff_at + RESULT_DELAY, m.result.home_goals + m.result.away_goals > 2.5)
        for m in matches
    )
    times = [k[0] for k in known]
    cum = np.cumsum([k[1] for k in known])

    def rate(at: datetime) -> float | None:
        n = bisect.bisect_left(times, at)
        return float(cum[n - 1] / n) if n else None

    return rate


def build_samples(
    rows: list[Row], odds: dict[Any, GoalMarketOdds], rates: dict[str, Any], params: ModelParams
) -> tuple[Sample, Sample, dict[str, int]]:
    ou: dict[str, list] = {k: [] for k in Sample.__slots__ if k != "market"}
    ah: dict[str, list] = {k: [] for k in Sample.__slots__ if k != "market"}
    dropped = {"no_over_under": 0, "no_handicap": 0}
    for r in rows:
        o = odds.get(match_key(r.match.result))
        res = r.match.result
        m = score_matrix(
            max(r.lam_h, params.min_lambda),
            max(r.lam_a, params.min_lambda),
            params.max_goals,
            params.dixon_coles_rho,
        )
        naive_over = rates[r.league](r.fitted_at)
        if o and o.over25 and o.under25 and naive_over is not None:
            over = res.home_goals + res.away_goals > 2.5
            p = over_probability(m)
            for key, value in (
                ("rows", r),
                ("won", float(over)),
                ("lost", float(not over)),
                ("model", p),
                ("market_p", two_way_devig(o.over25, o.under25)),
                ("naive", naive_over),
                ("model_won", p),
                ("model_lost", 1 - p),
                ("price_a", o.over25),
                ("price_b", o.under25),
                ("line", 2.5),
            ):
                ou[key].append(value)
        else:
            dropped["no_over_under"] += 1
        if o and o.handicap is not None and o.handicap_home and o.handicap_away:
            won, lost = settle(res.home_goals - res.away_goals, o.handicap)
            exp_won, exp_lost = handicap_shares(m, o.handicap)
            for key, value in (
                ("rows", r),
                ("won", won),
                ("lost", lost),
                ("model", exp_won / (exp_won + exp_lost)),
                ("market_p", two_way_devig(o.handicap_home, o.handicap_away)),
                ("naive", 0.5),
                ("model_won", exp_won),
                ("model_lost", exp_lost),
                ("price_a", o.handicap_home),
                ("price_b", o.handicap_away),
                ("line", o.handicap),
            ):
                ah[key].append(value)
        else:
            dropped["no_handicap"] += 1

    def make(name: str, cols: dict[str, list]) -> Sample:
        arrays = {k: (v if k == "rows" else np.asarray(v, dtype=float)) for k, v in cols.items()}
        return Sample(market=name, **arrays)

    return make("over_under_2_5", ou), make("asian_handicap", ah), dropped


def market_report(s: Sample, codes: list[str]) -> dict[str, Any]:
    validation = segment(s, s.mask(VALIDATION))
    follow_up = segment(s, s.mask(FOLLOW_UP))
    fu = s.mask(FOLLOW_UP)
    report: dict[str, Any] = {
        "n_matches": len(s.rows),
        "validation": validation,
        "follow_up": follow_up,
        "decision": decide(validation, follow_up),
        "descriptive": {
            "per_league_follow_up": {c: segment(s, s.mask(FOLLOW_UP, c)) for c in codes},
            "flagged_prices": {
                "note": "descriptive; the product never places bets",
                "validation": flags(s, s.mask(VALIDATION)),
                "follow_up": flags(s, fu),
            },
        },
    }
    if s.market == "asian_handicap":
        half = fu & (np.mod(s.line * 2, 2) == 1)  # x.5 lines: never a push
        report["descriptive"]["half_lines_follow_up"] = segment(s, half)
        lines, counts = np.unique(s.line[fu], return_counts=True)
        report["descriptive"]["lines_follow_up"] = {
            f"{v:+.2f}": int(c) for v, c in zip(lines, counts, strict=True)
        }
    else:
        totals = np.array([r.lam_h + r.lam_a for r in s.rows])
        goals = np.array([r.match.result.home_goals + r.match.result.away_goals for r in s.rows])
        report["descriptive"]["mean_total_goals_follow_up"] = {
            "predicted": float(totals[fu].mean()),
            "observed": float(goals[fu].mean()),
        }
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    params = ModelParams()
    rows: list[Row] = []
    odds: dict[Any, GoalMarketOdds] = {}
    rates: dict[str, Any] = {}
    counts: dict[str, dict[str, int]] = {}
    for code in codes:
        matches, counts[code] = club_match_data.load(code, FIRST, LAST, args.cache_dir)
        odds.update(club_match_data.load_goal_odds(code, args.cache_dir))
        rates[code] = over_rate_lookup(matches)
        logger.info("goal markets %s: %d matches", code, len(matches))
        rows += production_rows(
            code,
            matches,
            params,
            counts[code].get(FIRST, 0),
            [WARMUP[0], VALIDATION[0], FOLLOW_UP[0]],
        )
    ou, ah, dropped = build_samples(rows, odds, rates, params)
    path = club_match_data.fetch(args.cache_dir)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "goal_markets_v1",
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "protocol": __doc__,
        "source": {
            "url": club_match_data.URL,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "attribution": "football-data.co.uk via xgabora/Club-Football-Match-Data (MIT)",
        },
        "leagues": codes,
        "matches_per_season": counts,
        "n_predicted": len(rows),
        "dropped": dropped,
        "markets": {
            "over_under_2_5": market_report(ou, codes),
            "asian_handicap": market_report(ah, codes),
        },
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
