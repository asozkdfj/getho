"""Closing line value statistics: does the market move toward a forecast?

x = forecast - early price, y = close - early price (fair probabilities, all
three outcomes stacked). The plain slope sum(x y) / sum(x x) is positive even
for a forecaster with no information when early prices are noisy (any pull
toward the average "predicts" part of the move), so the partial slope also
regresses on base - early and reads the forecast's own coefficient.
"""

from __future__ import annotations

from typing import Any

import numpy as np

N_RESAMPLES = 4000


def _ids(clusters: np.ndarray | list[Any]) -> np.ndarray:
    _, ids = np.unique(np.asarray([str(c) for c in clusters]), return_inverse=True)
    return ids


def plain_slope(
    forecast: np.ndarray, early: np.ndarray, close: np.ndarray, clusters: Any, seed: int
) -> dict[str, Any]:
    x, y = forecast - early, close - early
    sxy, sxx = (x * y).sum(axis=1), (x * x).sum(axis=1)
    if len(sxx) == 0 or sxx.sum() <= 0:
        return {"n": len(sxx), "beta": None, "ci95": [None, None]}
    ids = _ids(clusters)
    w_xy, w_xx = np.bincount(ids, weights=sxy), np.bincount(ids, weights=sxx)
    idx = np.random.default_rng(seed).integers(0, len(w_xy), size=(N_RESAMPLES, len(w_xy)))
    den = w_xx[idx].sum(axis=1)
    boot = w_xy[idx].sum(axis=1) / np.where(den > 0, den, np.nan)
    return {
        "n": len(sxx),
        "clusters": len(w_xy),
        "beta": float(sxy.sum() / sxx.sum()),
        "ci95": [float(v) for v in np.nanquantile(boot, [0.025, 0.975])],
    }


def partial_slope(
    forecast: np.ndarray,
    base: np.ndarray,
    early: np.ndarray,
    close: np.ndarray,
    clusters: Any,
    seed: int,
) -> dict[str, Any]:
    """close - early = b_forecast (forecast - early) + b_base (base - early)."""
    x1, x2, y = forecast - early, base - early, close - early
    parts = np.stack(
        [(x1 * x1).sum(1), (x1 * x2).sum(1), (x2 * x2).sum(1), (x1 * y).sum(1), (x2 * y).sum(1)],
        axis=1,
    )
    empty = {"n": len(parts), "b_forecast": None, "b_forecast_ci95": [None, None]}
    if len(parts) == 0:
        return empty

    def solve(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a11, a12, a22, c1, c2 = t.T
        det = a11 * a22 - a12 * a12
        det = np.where(np.abs(det) > 1e-12, det, np.nan)
        return (a22 * c1 - a12 * c2) / det, (a11 * c2 - a12 * c1) / det

    b_f, b_b = solve(parts.sum(0, keepdims=True))
    if not np.isfinite(b_f[0]):
        return empty
    ids = _ids(clusters)
    weekly = np.stack([np.bincount(ids, weights=parts[:, j]) for j in range(5)], axis=1)
    idx = np.random.default_rng(seed).integers(0, len(weekly), size=(N_RESAMPLES, len(weekly)))
    boot_f, boot_b = solve(weekly[idx].sum(axis=1))
    return {
        "n": len(parts),
        "clusters": len(weekly),
        "b_forecast": float(b_f[0]),
        "b_forecast_ci95": [float(v) for v in np.nanquantile(boot_f, [0.025, 0.975])],
        "b_base": float(b_b[0]),
        "b_base_ci95": [float(v) for v in np.nanquantile(boot_b, [0.025, 0.975])],
    }
