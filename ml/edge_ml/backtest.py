"""Walk-forward (expanding window) backtest for 1X2 forecasters.

Leakage rules, enforced here rather than trusted to callers:
- forecasters are refitted at ``as_of`` = start of each window, on matches whose
  kickoff is strictly before ``as_of``;
- they then predict only matches with kickoff in [as_of, as_of + refit window);
- results of the predicted window are never visible to that fit.

All forecasters are scored on the SAME matches (those every forecaster could
predict) so differences are like-for-like. Uncertainty is reported with
bootstrap confidence intervals, including paired differences vs a reference.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from edge_ml.forecasters import BacktestMatch, Forecaster
from edge_ml.metrics import (
    OUTCOME_NAMES,
    accuracy_per_match,
    bootstrap_mean_ci,
    brier_per_match,
    calibration_bins,
    expected_calibration_error,
    log_loss_per_match,
    rps_per_match,
)


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    eval_start: datetime
    eval_end: datetime | None = None
    refit_every: timedelta = timedelta(days=7)
    min_history: int = 380  # need at least ~one season before forecasting
    reference: str | None = None  # forecaster used for paired comparisons
    bootstrap_resamples: int = 2000
    # A finished match only enters the training history this long after kickoff
    # (an assumed result-availability lag; 0 keeps the historical convention).
    result_delay: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.refit_every <= timedelta(0):
            raise ValueError("refit_every must be positive")
        if self.result_delay < timedelta(0):
            raise ValueError("result_delay must be nonnegative")


@dataclass(slots=True)
class Predictions:
    """Raw walk-forward output: per-forecaster probabilities on a common sample."""

    matches: list[BacktestMatch] = field(default_factory=list)
    probs: dict[str, np.ndarray] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    fitted_at: list[datetime] = field(default_factory=list)  # model fit time per match

    @property
    def outcomes(self) -> np.ndarray:
        return np.array([m.outcome_index for m in self.matches], dtype=int)


def walk_forward(
    matches: Sequence[BacktestMatch],
    forecasters: Sequence[Forecaster],
    config: BacktestConfig,
) -> Predictions:
    ordered = sorted(matches, key=lambda m: (m.result.kickoff_at, m.result.home, m.result.away))
    if not ordered:
        return Predictions(probs={f.name: np.empty((0, 3)) for f in forecasters})
    results = [m.result for m in ordered]
    end = config.eval_end or (ordered[-1].result.kickoff_at + timedelta(seconds=1))
    raw: dict[str, list[tuple[float, float, float] | None]] = {f.name: [] for f in forecasters}
    evaluated: list[BacktestMatch] = []
    fitted_at: list[datetime] = []

    as_of = config.eval_start
    while as_of < end:
        window_end = min(as_of + config.refit_every, end)
        window = [m for m in ordered if as_of <= m.result.kickoff_at < window_end]
        if window:
            history = [r for r in results if r.kickoff_at + config.result_delay < as_of]
            if len(history) >= config.min_history:
                # hard leakage guard
                assert all(r.kickoff_at < as_of for r in history)
                for f in forecasters:
                    f.fit(history, as_of)
                for m in window:
                    evaluated.append(m)
                    fitted_at.append(as_of)
                    for f in forecasters:
                        p = f.predict(m)
                        raw[f.name].append(None if p is None else p.as_tuple())
        as_of = window_end

    keep = [
        i for i in range(len(evaluated)) if all(raw[f.name][i] is not None for f in forecasters)
    ]
    out = Predictions(matches=[evaluated[i] for i in keep], fitted_at=[fitted_at[i] for i in keep])
    for f in forecasters:
        out.skipped[f.name] = sum(1 for p in raw[f.name] if p is None)
        out.probs[f.name] = np.array([raw[f.name][i] for i in keep], dtype=float).reshape(-1, 3)
    return out


def _summary(values: np.ndarray, resamples: int) -> dict[str, float]:
    lo, hi = bootstrap_mean_ci(values, n_resamples=resamples)
    return {"mean": float(values.mean()), "ci_low": lo, "ci_high": hi}


def evaluate(preds: Predictions, config: BacktestConfig) -> dict[str, Any]:
    """Metrics per forecaster, per season and per outcome, plus paired comparisons."""
    y = preds.outcomes
    n = len(y)
    if n == 0:
        return {"n_matches": 0, "models": {}}
    seasons = [m.result.season or "unknown" for m in preds.matches]
    season_idx: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(seasons):
        season_idx[s].append(i)

    observed = {name: float((y == k).mean()) for k, name in enumerate(OUTCOME_NAMES)}
    report: dict[str, Any] = {
        "n_matches": n,
        "first_kickoff": preds.matches[0].result.kickoff_at.isoformat(),
        "last_kickoff": preds.matches[-1].result.kickoff_at.isoformat(),
        "observed_frequency": observed,
        "skipped_matches": preds.skipped,
        "models": {},
    }
    per_match: dict[str, dict[str, np.ndarray]] = {}
    for name, p in preds.probs.items():
        ll, br, rps, acc = (
            log_loss_per_match(p, y),
            brier_per_match(p, y),
            rps_per_match(p, y),
            accuracy_per_match(p, y),
        )
        per_match[name] = {"log_loss": ll, "brier": br, "rps": rps}
        report["models"][name] = {
            "log_loss": _summary(ll, config.bootstrap_resamples),
            "brier": _summary(br, config.bootstrap_resamples),
            "rps": _summary(rps, config.bootstrap_resamples),
            "accuracy": float(acc.mean()),
            "ece": expected_calibration_error(p, y),
            "mean_predicted": {k: float(p[:, i].mean()) for i, k in enumerate(OUTCOME_NAMES)},
            "per_season": {
                s: {
                    "n": len(idx),
                    "log_loss": float(ll[idx].mean()),
                    "brier": float(br[idx].mean()),
                    "accuracy": float(acc[idx].mean()),
                }
                for s, idx in sorted(season_idx.items())
            },
            "calibration": [
                b.__dict__ if hasattr(b, "__dict__") else _bin(b) for b in calibration_bins(p, y)
            ],
        }
    ref = config.reference
    if ref and ref in per_match:
        for name in per_match:
            if name == ref:
                continue
            diffs = {}
            for metric in ("log_loss", "brier", "rps"):
                d = per_match[name][metric] - per_match[ref][metric]
                lo, hi = bootstrap_mean_ci(d, n_resamples=config.bootstrap_resamples, seed=1)
                diffs[metric] = {
                    "mean_diff": float(d.mean()),
                    "ci_low": lo,
                    "ci_high": hi,
                    # negative = better than the reference; "significant" if CI excludes 0
                    "better_than_reference": bool(hi < 0),
                    "worse_than_reference": bool(lo > 0),
                }
            report["models"][name]["vs_reference"] = {"reference": ref, **diffs}
    return report


def _bin(b: Any) -> dict[str, Any]:
    return {s: getattr(b, s) for s in b.__slots__}
