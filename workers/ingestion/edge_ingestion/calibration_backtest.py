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


def walk_forward(method: str, probs: np.ndarray, y: np.ndarray, seasons: np.ndarray) -> np.ndarray:
    """Calibrated probabilities; each season mapped with earlier seasons only
    (the first season is left as it is and never evaluated)."""
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
    return out


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

    candidates = {m: walk_forward(m, probs, y, seasons) for m in METHODS}

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

    def crossing(p: np.ndarray) -> dict[str, float]:
        top = p[fu][np.arange(fu.sum()), top_index(p[fu])]
        return {
            "share_ge_55": float((top >= 0.55).mean()),
            "share_ge_65": float((top >= 0.65).mean()),
        }

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "top_outcome_calibration_v1",
        "protocol": __doc__,
        "source": {
            "path": str(args.predictions),
            "sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
        },
        "n_matches": len(rows),
        "chosen": chosen,
        "validation": v,
        "follow_up": f,
        "gate": gates,
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
