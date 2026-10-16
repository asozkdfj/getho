"""Shared engine for "does feature group X improve the production model?" experiments.

Every experiment uses the same steps so the results compare:
1. Walk-forward production expected goals (weekly refit, results enter training
   3 h after kickoff; the refit grid restarts at the warm-up, validation and
   follow-up starts, like the QA replay).
2. For each feature variant, coefficients of
       log lam_own' = log lam_own + a . x_own - b . x_opp
   refitted before each season on every earlier season (Poisson MLE with the
   production expected goals as offsets), then applied to that season.
3. Metrics per segment and a pre-registered gate on the variant chosen on the
   validation seasons.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from edge_ml.core import Probabilities1X2
from edge_ml.fatigue import adjust, fit
from edge_ml.forecasters import BacktestMatch
from edge_ml.metrics import (
    accuracy_per_match,
    brier_per_match,
    cluster_bootstrap_ci,
    expected_calibration_error,
    log_loss_per_match,
)
from edge_ml.model import ModelParams, PoissonEloModel
from edge_ml.poisson import probabilities_from_expected_goals

RESULT_DELAY = timedelta(hours=3)
REFIT_EVERY = timedelta(days=7)
MIN_VALIDATION_GAIN, MIN_FOLLOW_UP_GAIN = 0.001, 0.002


@dataclass(slots=True)
class Row:
    league: str
    match: BacktestMatch
    fitted_at: datetime
    lam_h: float
    lam_a: float
    production: tuple[float, float, float]


def season_start(matches: Sequence[BacktestMatch], season: str) -> datetime:
    return min(m.result.kickoff_at for m in matches if m.result.season == season)


def production_rows(
    league: str,
    matches: Sequence[BacktestMatch],
    params: ModelParams,
    min_history: int,
    anchor_seasons: Sequence[str],
) -> list[Row]:
    ordered = sorted(matches, key=lambda m: (m.result.kickoff_at, m.result.home, m.result.away))
    results = [m.result for m in ordered]
    anchors = [season_start(ordered, s) for s in anchor_seasons]
    ends = [*anchors[1:], ordered[-1].result.kickoff_at + timedelta(seconds=1)]
    rows: list[Row] = []
    for start, end in zip(anchors, ends, strict=True):
        as_of = start
        while as_of < end:
            window_end = min(as_of + REFIT_EVERY, end)
            window = [m for m in ordered if as_of <= m.result.kickoff_at < window_end]
            history = [r for r in results if r.kickoff_at + RESULT_DELAY < as_of]
            if window and len(history) >= min_history:
                model = PoissonEloModel(params=params).fit(history, as_of)
                for m in window:
                    out = model.predict(m.result.home, m.result.away)
                    rows.append(
                        Row(
                            league,
                            m,
                            as_of,
                            out.expected_goals_home,
                            out.expected_goals_away,
                            out.probabilities.as_tuple(),
                        )
                    )
            as_of = window_end
    return rows


def probs_from_lambdas(lam_h: np.ndarray, lam_a: np.ndarray, params: ModelParams) -> np.ndarray:
    out = []
    for h, a in zip(lam_h, lam_a, strict=True):
        p = probabilities_from_expected_goals(
            max(float(h), params.min_lambda),
            max(float(a), params.min_lambda),
            params.max_goals,
            params.dixon_coles_rho,
        )
        if params.draw_inflation != 1.0:
            p = Probabilities1X2.normalized(p.home, p.draw * params.draw_inflation, p.away)
        out.append(p.as_tuple())
    return np.asarray(out, dtype=float).reshape(-1, 3)


def metrics(probs: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {
        "log_loss": float(log_loss_per_match(probs, y).mean()),
        "brier": float(brier_per_match(probs, y).mean()),
        "accuracy": float(accuracy_per_match(probs, y).mean()),
        "ece": float(expected_calibration_error(probs, y)),
    }


def compare(cand: np.ndarray, prod: np.ndarray, y: np.ndarray, rows: list[Row]) -> dict[str, Any]:
    diff = log_loss_per_match(cand, y) - log_loss_per_match(prod, y)
    weeks = [r.match.result.kickoff_at.isocalendar()[:2] for r in rows]
    lo, hi = cluster_bootstrap_ci(diff, weeks)
    return {
        "log_loss_diff": float(diff.mean()),
        "log_loss_diff_ci95_weekly": [lo, hi],
        "brier_diff": float((brier_per_match(cand, y) - brier_per_match(prod, y)).mean()),
        "accuracy_diff": float((accuracy_per_match(cand, y) - accuracy_per_match(prod, y)).mean()),
        "weeks": len(set(weeks)),
    }


FeatureFn = Callable[[list[Row]], tuple[np.ndarray, np.ndarray]]


@dataclass(slots=True)
class Experiment:
    rows: list[Row]
    production: np.ndarray
    candidates: dict[str, np.ndarray]
    coefficients: dict[str, dict[str, Any]]

    @property
    def seasons(self) -> np.ndarray:
        return np.array([r.match.result.season for r in self.rows])

    @property
    def outcomes(self) -> np.ndarray:
        return np.array([r.match.outcome_index for r in self.rows], dtype=int)

    def segment(self, seasons: Sequence[str], league: str | None = None) -> dict[str, Any]:
        mask = np.isin(self.seasons, list(seasons))
        if league is not None:
            mask &= np.array([r.league == league for r in self.rows])
        y = self.outcomes
        sub = [r for r, k in zip(self.rows, mask, strict=True) if k]
        out: dict[str, Any] = {
            "seasons": list(seasons),
            "n_matches": int(mask.sum()),
            "production": metrics(self.production[mask], y[mask]),
        }
        for name, p in self.candidates.items():
            out[name] = {
                **metrics(p[mask], y[mask]),
                "vs_production": compare(p[mask], self.production[mask], y[mask], sub),
            }
        return out


def run_variants(
    rows: list[Row],
    variants: dict[str, FeatureFn],
    target_seasons: Sequence[str],
    params: ModelParams,
) -> Experiment:
    seasons = np.array([r.match.result.season for r in rows])
    lam_h = np.array([r.lam_h for r in rows])
    lam_a = np.array([r.lam_a for r in rows])
    goals_h = np.array([r.match.result.home_goals for r in rows], dtype=float)
    goals_a = np.array([r.match.result.away_goals for r in rows], dtype=float)
    prod = np.asarray([r.production for r in rows], dtype=float)
    # The adjusted model with zero coefficients must be the production model.
    assert np.allclose(probs_from_lambdas(lam_h, lam_a, params), prod, atol=1e-9)

    candidates: dict[str, np.ndarray] = {}
    coefficients: dict[str, dict[str, Any]] = {}
    for name, features in variants.items():
        x_h, x_a = features(rows)
        probs = prod.copy()
        coefficients[name] = {}
        for season in target_seasons:
            train = seasons < season  # every earlier season
            target = seasons == season
            f = fit(
                lam_h[train], lam_a[train], x_h[train], x_a[train], goals_h[train], goals_a[train]
            )
            coefficients[name][season] = {
                "own": f.own,
                "opponent": f.opponent,
                "n_matches": f.n_matches,
                "log_likelihood_gain": f.log_likelihood_gain,
            }
            adj_h, adj_a = adjust(
                lam_h[target], lam_a[target], x_h[target], x_a[target], f.own, f.opponent
            )
            probs[target] = probs_from_lambdas(adj_h, adj_a, params)
        candidates[name] = probs
    return Experiment(rows, prod, candidates, coefficients)


def gate(
    validation: dict[str, Any], follow_up: dict[str, Any], candidates: Sequence[str]
) -> dict[str, Any]:
    chosen = min(candidates, key=lambda v: validation[v]["log_loss"])
    v_gain = validation["production"]["log_loss"] - validation[chosen]["log_loss"]
    fu = follow_up[chosen]["vs_production"]
    checks = {
        "validation_gain>=0.001": v_gain >= MIN_VALIDATION_GAIN,
        "follow_up_gain>=0.002": -fu["log_loss_diff"] >= MIN_FOLLOW_UP_GAIN,
        "weekly_ci_upper<0": fu["log_loss_diff_ci95_weekly"][1] < 0,
        "brier_not_worse": fu["brier_diff"] <= 0,
    }
    return {
        "selected_on_validation": chosen,
        "validation_gain": v_gain,
        "follow_up_gain": -fu["log_loss_diff"],
        "checks": checks,
        "passes": all(checks.values()),
        "deployed": False,
    }


def write_predictions(path: Any, experiments: Sequence[Experiment]) -> None:
    import json

    with path.open("w", encoding="utf-8") as f:
        for ex in experiments:
            for i, r in enumerate(ex.rows):
                m = r.match.result
                row = {
                    "league": r.league,
                    "season": m.season,
                    "kickoff_at": m.kickoff_at.isoformat(),
                    "home": m.home,
                    "away": m.away,
                    "fitted_at": r.fitted_at.isoformat(),
                    "outcome": r.match.outcome_index,
                    "production": [round(v, 6) for v in ex.production[i]],
                    **{k: [round(v, 6) for v in p[i]] for k, p in ex.candidates.items()},
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
