"""`edge backtest-calibration` - are clear favourites under-stated, and can a
calibration of the top outcome fix it?

Pre-registered protocol (committed before the first run; do not edit after results):

Question  On 2023-26 the production model's most likely outcome won 3.5-4.4
          points more often than it said when it said 60% or more, while the
          40-60% range was close (user feedback: "the probabilities look low").
          Does a monotone recalibration of the top outcome fix the favourites
          without making anything else worse?
Data      Per-match walk-forward production probabilities of the market
          baseline experiment (ml/reports/backtest-market.predictions.jsonl.gz:
          9 leagues, football-data.co.uk results, weekly refit, results enter
          training 3 h after kickoff), seasons 2019-20..2025-26; file SHA-256
          in the report. The production model itself is not refitted.
Method    TopOutcomeCalibrator (edge_ml.calibration): g maps the top outcome's
          probability; the other two keep their ratio and share 1 - g; the top
          outcome stays on top. Candidates: "logistic" (Platt, 2 parameters)
          and "isotonic" (pool-adjacent-violators).
Timing    Season walk-forward: the map applied to season S is fitted only on the
          seasons before S in the file (2020-21 uses 2019-20; 2025-26 uses
          2019-20..2024-25). No season is ever calibrated with its own results.
Choice    The candidate with the lowest pooled log loss on validation
          (2020-21..2022-23).
Gate      All, for the chosen candidate against production:
          G1 validation: pooled log loss gain > 0.
          G2 follow-up (2023-24..2025-26): pooled log loss gain >= 0 and Brier
             gain >= 0 (weekly paired 95% CI reported).
          G3 follow-up, matches whose production top probability is >= 0.60:
             |hit rate - mean calibrated top probability| <= 0.015.
          G4 follow-up, matches below 0.60: that gap does not grow by more
             than 0.005 versus production.
          Passing is a research result only. Using the calibrator in the
          service is a model change (new model version, Codex QA, the user's
          approval) and changes which matches clear the pick and tier
          thresholds; it is not done automatically.
Descriptive (no decision): calibration by top-probability band; the share of
          matches that cross the 55% / 65% tiers; the daily top-3 combination
          (most likely outcomes of a KST 09:00-09:00 day) predicted vs actual
          hit rate, before and after.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from edge_ml.calibration import TopOutcomeCalibrator
from edge_ml.metrics import cluster_bootstrap_ci

logger = logging.getLogger(__name__)

PREDICTIONS = Path("ml/reports/backtest-market.predictions.jsonl.gz")
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25", "2025-26"]
METHODS = ("logistic", "isotonic")
TIER = 0.60
MAX_TIER_GAP = 0.015
MAX_GAP_GROWTH = 0.005
BANDS = ((0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01))
EPS = 1e-12
# Status, added after the first results following Codex QA (M1, 2026-10-18); the
# protocol above stays as it was. The follow-up seasons had already been looked
# at (market baseline experiment, band exploration that motivated this one), so
# they are not an independent holdout, and G1-G2 are weaker than the standard
# promotion gate. The result is exploratory; the confirmatory test is
# docs/experiments/calibration-confirmatory-2026-27.md.
STATUS = "exploratory"
PROTOCOL_COMMIT = "cd8846f"
STANDARD_GATE = {"validation_gain": 0.001, "follow_up_gain": 0.002, "ci_upper_below": 0.0}
RESULTS_DELAY = timedelta(hours=3)  # results enter training 3 h after kickoff


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--predictions", type=Path, default=PREDICTIONS)
    p.add_argument("--out", type=Path, help="write the JSON report here")


def load(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt") as fh:
        return [json.loads(line) for line in fh]


def top_index(probs: np.ndarray) -> np.ndarray:
    order = np.array([0, 2, 1])  # HOME > AWAY > DRAW on ties
    return order[np.argmax(probs[:, order], axis=1)]


def log_loss(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probs[np.arange(len(y)), y], EPS, 1))


def brier(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    onehot = np.eye(3)[y]
    return ((probs - onehot) ** 2).sum(axis=1)


def walk_forward(
    method: str,
    probs: np.ndarray,
    y: np.ndarray,
    seasons: np.ndarray,
    history: list[TopOutcomeCalibrator] | None = None,
) -> np.ndarray:
    """Calibrated probabilities; each season mapped with earlier seasons only
    (the first season is left as it is and never evaluated). The fitted maps,
    one per target season in order, are appended to ``history`` if given."""
    out = probs.copy()
    order = sorted(set(seasons.tolist()))
    k = top_index(probs)
    top = probs[np.arange(len(y)), k]
    hit = (k == y).astype(float)
    for i, season in enumerate(order[1:], start=1):
        train = np.isin(seasons, order[:i])
        target = seasons == season
        cal = TopOutcomeCalibrator(method).fit_arrays(top[train], hit[train])
        out[target] = cal.calibrate_matrix(probs[target])
        if history is not None:
            history.append(cal)
    return out


def _map_params(cal: TopOutcomeCalibrator) -> dict[str, Any]:
    if cal.method == "logistic":
        a, b = cal.params
        return {"a": a, "b": b}
    xs, ys = cal.knots
    return {"knots": len(xs), "x": [float(v) for v in xs], "y": [float(v) for v in ys]}


def parameter_history(
    rows: list[dict[str, Any]], seasons: np.ndarray, maps: list[TopOutcomeCalibrator]
) -> list[dict[str, Any]]:
    """For each target season: which seasons the map saw, its parameters, when it
    is first used (the season's first kickoff) and when its training data were
    complete (last training kickoff + the results delay)."""
    order = sorted(set(seasons.tolist()))
    kickoffs = np.array([datetime.fromisoformat(r["kickoff_at"]) for r in rows])
    out = []
    for i, cal in enumerate(maps, start=1):
        train = np.isin(seasons, order[:i])
        available = kickoffs[train].max() + RESULTS_DELAY
        decision = kickoffs[seasons == order[i]].min()
        assert available <= decision, f"map for {order[i]} uses data after its first kickoff"
        out.append(
            {
                "season": order[i],
                "trained_on": order[:i],
                "n_train": int(train.sum()),
                "available_at": available.isoformat(),
                "decision_at": decision.isoformat(),
                **_map_params(cal),
            }
        )
    return out


def breakdown(
    keys: np.ndarray,
    probs: np.ndarray,
    cal: np.ndarray,
    y: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    """Log loss and strong-favourite gap per group (descriptive, no decision)."""
    k_ref = top_index(probs)
    ref_top = probs[np.arange(len(y)), k_ref]
    out = {}
    for key in sorted(set(keys[mask].tolist())):
        m = mask & (keys == key)
        strong = m & (ref_top >= TIER)
        out[key] = {
            "n": int(m.sum()),
            "log_loss_production": float(log_loss(probs[m], y[m]).mean()),
            "log_loss_calibrated": float(log_loss(cal[m], y[m]).mean()),
            "log_loss_gain": float(log_loss(probs[m], y[m]).mean() - log_loss(cal[m], y[m]).mean()),
            "n_strong": int(strong.sum()),
            "strong_gap_production": tier_gap(probs, y, strong) if strong.any() else None,
            "strong_gap_calibrated": tier_gap(cal, y, strong) if strong.any() else None,
        }
    return out


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def bands(
    probs: np.ndarray, y: np.ndarray, ref: np.ndarray, mask: np.ndarray
) -> list[dict[str, Any]]:
    """Calibration of the top outcome, banded by the reference (production) top."""
    k_ref = top_index(ref)
    ref_top = ref[np.arange(len(y)), k_ref]
    k = top_index(probs)
    top = probs[np.arange(len(y)), k]
    hit = k == y
    rows = []
    for lo, hi in BANDS:
        m = mask & (ref_top >= lo) & (ref_top < hi)
        if m.sum():
            rows.append(
                {
                    "band": [lo, min(hi, 1.0)],
                    "n": int(m.sum()),
                    "mean_predicted": float(top[m].mean()),
                    "hit_rate": float(hit[m].mean()),
                    "gap": float(hit[m].mean() - top[m].mean()),
                }
            )
    return rows


def tier_gap(probs: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float:
    k = top_index(probs)
    top = probs[np.arange(len(y)), k]
    return float(abs((k == y)[mask].mean() - top[mask].mean()))


def daily_top3(
    rows: list[dict[str, Any]], probs: np.ndarray, y: np.ndarray, mask: np.ndarray
) -> dict[str, Any]:
    """Each KST 09:00->09:00 day: the three matches with the most likely outcomes."""
    kst = ZoneInfo("Asia/Seoul")
    days: dict[Any, list[int]] = defaultdict(list)
    for i in np.flatnonzero(mask):
        at = datetime.fromisoformat(rows[i]["kickoff_at"]).astimezone(kst) - timedelta(hours=9)
        days[at.date()].append(int(i))
    k = top_index(probs)
    top = probs[np.arange(len(y)), k]
    claimed, hits = [], []
    for idx in days.values():
        if len(idx) < 3:
            continue
        best = sorted(idx, key=lambda i: -top[i])[:3]
        claimed.append(float(np.prod(top[best])))
        hits.append(all(k[i] == y[i] for i in best))
    return {
        "days": len(claimed),
        "mean_predicted": float(np.mean(claimed)) if claimed else None,
        "hit_rate": float(np.mean(hits)) if hits else None,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    rows = load(args.predictions)
    probs = np.array([r["production"] for r in rows], dtype=float)
    y = np.array([r["outcome"] for r in rows], dtype=int)
    seasons = np.array([r["season"] for r in rows])
    weeks = [datetime.fromisoformat(r["kickoff_at"]).isocalendar()[:2] for r in rows]
    val, fu = np.isin(seasons, VALIDATION), np.isin(seasons, FOLLOW_UP)

    leagues = np.array([r.get("league", "unknown") for r in rows])
    maps: dict[str, list[TopOutcomeCalibrator]] = {m: [] for m in METHODS}
    candidates = {m: walk_forward(m, probs, y, seasons, maps[m]) for m in METHODS}

    def summary(p: np.ndarray, mask: np.ndarray) -> dict[str, float]:
        return {
            "log_loss": float(log_loss(p[mask], y[mask]).mean()),
            "brier": float(brier(p[mask], y[mask]).mean()),
            "accuracy": float((top_index(p[mask]) == y[mask]).mean()),
        }

    def paired(p: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
        diff = log_loss(p[mask], y[mask]) - log_loss(probs[mask], y[mask])
        wk = [w for w, m in zip(weeks, mask, strict=True) if m]
        lo, hi = cluster_bootstrap_ci(diff, wk)
        return {"log_loss_diff": float(diff.mean()), "ci95_weekly": [lo, hi]}

    segments: dict[str, Any] = {}
    for name, mask in (("validation", val), ("follow_up", fu)):
        segments[name] = {
            "n_matches": int(mask.sum()),
            "production": summary(probs, mask),
            **{
                m: {**summary(p, mask), "vs_production": paired(p, mask)}
                for m, p in candidates.items()
            },
        }

    chosen = min(METHODS, key=lambda m: segments["validation"][m]["log_loss"])
    cal = candidates[chosen]
    v, f = segments["validation"], segments["follow_up"]
    ref_top = probs[np.arange(len(y)), top_index(probs)]
    strong, rest = fu & (ref_top >= TIER), fu & (ref_top < TIER)
    gates = {
        "g1_validation_gain": v["production"]["log_loss"] - v[chosen]["log_loss"],
        "g2_follow_up_log_loss_gain": f["production"]["log_loss"] - f[chosen]["log_loss"],
        "g2_follow_up_brier_gain": f["production"]["brier"] - f[chosen]["brier"],
        "g3_strong_tier_gap": tier_gap(cal, y, strong),
        "g3_strong_tier_gap_production": tier_gap(probs, y, strong),
        "g4_rest_gap": tier_gap(cal, y, rest),
        "g4_rest_gap_production": tier_gap(probs, y, rest),
    }
    gates["passed"] = bool(
        gates["g1_validation_gain"] > 0
        and gates["g2_follow_up_log_loss_gain"] >= 0
        and gates["g2_follow_up_brier_gain"] >= 0
        and gates["g3_strong_tier_gap"] <= MAX_TIER_GAP
        and gates["g4_rest_gap"] <= gates["g4_rest_gap_production"] + MAX_GAP_GROWTH
    )

    standard = {
        "validation_gain": gates["g1_validation_gain"],
        "follow_up_gain": gates["g2_follow_up_log_loss_gain"],
        "follow_up_ci95_weekly": f[chosen]["vs_production"]["ci95_weekly"],
    }
    standard["passed"] = bool(
        standard["validation_gain"] >= STANDARD_GATE["validation_gain"]
        and standard["follow_up_gain"] >= STANDARD_GATE["follow_up_gain"]
        and standard["follow_up_ci95_weekly"][1] < STANDARD_GATE["ci_upper_below"]
    )
    evaluated = val | fu
    final = TopOutcomeCalibrator(chosen).fit_arrays(ref_top, (top_index(probs) == y).astype(float))
    kickoffs = [datetime.fromisoformat(r["kickoff_at"]) for r in rows]

    def crossing(p: np.ndarray) -> dict[str, float]:
        top = p[fu][np.arange(fu.sum()), top_index(p[fu])]
        return {
            "share_ge_55": float((top >= 0.55).mean()),
            "share_ge_65": float((top >= 0.65).mean()),
        }

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "top_outcome_calibration_v1",
        "status": STATUS,
        "protocol": __doc__,
        "manifest": {
            "protocol_commit": PROTOCOL_COMMIT,
            "code_commit": _git_commit(),
            "input": str(args.predictions),
            "input_sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
            "rows": len(rows),
            "evaluated_rows": int(evaluated.sum()),
            "excluded": {
                "rows": int((~evaluated).sum()),
                "reason": "seasons outside validation and follow-up (the first season has "
                "no earlier season to fit a map on)",
            },
            "seasons": sorted(set(seasons.tolist())),
            "leagues": sorted(set(leagues.tolist())),
        },
        "source": {
            "path": str(args.predictions),
            "sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
        },
        "n_matches": len(rows),
        "chosen": chosen,
        "validation": v,
        "follow_up": f,
        "gate": gates,
        "standard_gate": {"thresholds": STANDARD_GATE, **standard},
        "parameter_history": {m: parameter_history(rows, seasons, maps[m]) for m in METHODS},
        "frozen_map_for_confirmation": {
            "method": chosen,
            "trained_on": sorted(set(seasons.tolist())),
            "n_train": len(rows),
            "available_at": (max(kickoffs) + RESULTS_DELAY).isoformat(),
            **_map_params(final),
        },
        "by_season": breakdown(seasons, probs, cal, y, evaluated),
        "by_league_follow_up": breakdown(leagues, probs, cal, y, fu),
        "descriptive": {
            "bands_follow_up": {
                "production": bands(probs, y, probs, fu),
                **{m: bands(p, y, probs, fu) for m, p in candidates.items()},
            },
            "tier_shares_follow_up": {
                "production": crossing(probs),
                **{m: crossing(p) for m, p in candidates.items()},
            },
            "daily_top3_follow_up": {
                "production": daily_top3(rows, probs, y, fu),
                **{m: daily_top3(rows, p, y, fu) for m, p in candidates.items()},
            },
        },
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
