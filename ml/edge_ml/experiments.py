"""Reproducible model experiments: tune on validation seasons, judge on test seasons.

Protocol (no information flows from test into any decision):
1. warm-up seasons    : history only, never scored
2. validation seasons : walk-forward scored; hyper-parameters are chosen here
3. test seasons       : walk-forward scored ONCE with the frozen choice; the
                        promotion decision is made on these numbers only

Hyper-parameters are searched one at a time (coordinate search) and a change
is adopted only if validation log loss improves by at least ``min_gain``; small
"improvements" on ~1,000 matches are mostly noise.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from edge_ml.backtest import BacktestConfig, Predictions, walk_forward
from edge_ml.calibration import TemperatureCalibrator
from edge_ml.core import Outcome, Probabilities1X2
from edge_ml.forecasters import (
    BacktestMatch,
    BaseRateForecaster,
    EloOnlyForecaster,
    Forecaster,
    MarketForecaster,
    ModelForecaster,
    SeasonBlindForecaster,
)
from edge_ml.model import ModelParams

# Search space: dotted path into ModelParams -> candidate values.
DEFAULT_GRID: dict[str, list[Any]] = {
    "poisson_weight": [0.0, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0],
    "strength.time_decay_per_day": [0.0, 0.001, 0.0025, 0.005, 0.0075, 0.01],
    "strength.prior_matches": [1.0, 2.0, 4.0, 8.0],
    "elo.k_factor": [10.0, 15.0, 20.0, 25.0, 30.0],
    "elo.home_advantage": [30.0, 45.0, 60.0, 75.0, 90.0],
    "elo.use_goal_difference_multiplier": [False, True],
    "elo_points_per_goal": [200.0, 240.0, 280.0, 320.0, 360.0],
    "dixon_coles_rho": [0.0, -0.03, -0.06, -0.1, -0.13],
    "newcomer_reference_teams": [1, 3, 5],
    "elo_season_regression": [0.0, 0.1, 0.2, 0.33],
    "draw_inflation": [0.95, 1.0, 1.05, 1.1, 1.15],
}


def set_param(params: ModelParams, path: str, value: Any) -> ModelParams:
    head, _, rest = path.partition(".")
    if not rest:
        return dataclasses.replace(params, **{head: value})
    inner = getattr(params, head)
    return dataclasses.replace(params, **{head: dataclasses.replace(inner, **{rest: value})})


def get_param(params: ModelParams, path: str) -> Any:
    obj: Any = params
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


@dataclass(frozen=True, slots=True)
class Split:
    validation_start: datetime
    test_start: datetime
    test_end: datetime | None = None


def _log_loss(
    matches: Sequence[BacktestMatch], f: Forecaster, start: datetime, end: datetime
) -> float:
    cfg = BacktestConfig(eval_start=start, eval_end=end, bootstrap_resamples=200)
    preds = walk_forward(matches, [f], cfg)
    p, y = preds.probs[f.name], preds.outcomes
    return float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1)).mean())


@dataclass(slots=True)
class TuningResult:
    params: ModelParams
    baseline_log_loss: float
    tuned_log_loss: float
    steps: list[dict[str, Any]] = field(default_factory=list)


def coordinate_search(
    matches: Sequence[BacktestMatch],
    split: Split,
    base: ModelParams,
    grid: dict[str, list[Any]] | None = None,
    min_gain: float = 0.001,
    rounds: int = 2,
    progress: Callable[[str], None] | None = None,
) -> TuningResult:
    grid = grid or DEFAULT_GRID
    start, end = split.validation_start, split.test_start
    best = base
    best_ll = baseline = _log_loss(matches, ModelForecaster("m", best), start, end)
    steps: list[dict[str, Any]] = []
    for r in range(rounds):
        changed = False
        for path, values in grid.items():
            current = get_param(best, path)
            scores = {}
            for v in values:
                scores[v] = (
                    best_ll
                    if v == current
                    else _log_loss(
                        matches, ModelForecaster("m", set_param(best, path, v)), start, end
                    )
                )
            v_best = min(scores, key=scores.__getitem__)
            gain = best_ll - scores[v_best]
            adopted = v_best != current and gain >= min_gain
            steps.append(
                {
                    "round": r + 1,
                    "param": path,
                    "from": current,
                    "best_value": v_best,
                    "validation_log_loss": {str(k): round(s, 5) for k, s in scores.items()},
                    "gain": round(gain, 5),
                    "adopted": adopted,
                }
            )
            if progress:
                progress(f"{path}: best={v_best} gain={gain:.4f} adopted={adopted}")
            if adopted:
                best, best_ll, changed = set_param(best, path, v_best), scores[v_best], True
        if not changed:
            break
    return TuningResult(best, baseline, best_ll, steps)


class CalibratedForecaster:
    """Wraps a forecaster with a calibrator fitted beforehand (on validation data)."""

    def __init__(self, inner: Forecaster, calibrator: TemperatureCalibrator, name: str) -> None:
        self.inner, self.calibrator, self.name = inner, calibrator, name

    def fit(self, history, as_of):  # type: ignore[no-untyped-def]
        self.inner.fit(history, as_of)
        return self

    def predict(self, match: BacktestMatch) -> Probabilities1X2 | None:
        p = self.inner.predict(match)
        return None if p is None else self.calibrator.calibrate(p)


def fit_temperature(preds: Predictions, name: str) -> TemperatureCalibrator:
    outcomes = [list(Outcome)[i] for i in preds.outcomes]
    probs = [Probabilities1X2.normalized(*row) for row in preds.probs[name]]
    return TemperatureCalibrator().fit(probs, outcomes)


def standard_forecasters(
    production: ModelParams, candidate: ModelParams | None, include_market: bool
) -> list[Forecaster]:
    fs: list[Forecaster] = [
        BaseRateForecaster(),
        EloOnlyForecaster(),
        ModelForecaster("poisson_only", dataclasses.replace(production, poisson_weight=1.0)),
        SeasonBlindForecaster("production_no_promoted_prior", production),
        ModelForecaster("production", production),
    ]
    if candidate is not None:
        fs.append(ModelForecaster("candidate", candidate))
    if include_market:
        fs.append(MarketForecaster())
    return fs


def params_to_dict(params: ModelParams) -> dict[str, Any]:
    return dataclasses.asdict(params)
