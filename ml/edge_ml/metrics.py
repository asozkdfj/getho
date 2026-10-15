"""Probabilistic forecast metrics for 1X2 (three ordered outcomes H, D, A).

All functions take ``probs`` with shape (n, 3) in HOME, DRAW, AWAY order and
``outcomes`` as integer class indices (0=HOME, 1=DRAW, 2=AWAY).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EPS = 1e-15
OUTCOME_NAMES = ("HOME", "DRAW", "AWAY")


def _check(probs: np.ndarray, outcomes: np.ndarray) -> None:
    if probs.ndim != 2 or probs.shape[1] != 3:
        raise ValueError("probs must have shape (n, 3)")
    if len(probs) != len(outcomes):
        raise ValueError("probs and outcomes must have the same length")
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("each probability row must sum to 1")


def one_hot(outcomes: np.ndarray) -> np.ndarray:
    return np.eye(3)[outcomes]


def log_loss_per_match(probs: np.ndarray, outcomes: np.ndarray) -> np.ndarray:
    """Negative log-likelihood of the observed outcome (natural log)."""
    _check(probs, outcomes)
    return -np.log(np.clip(probs[np.arange(len(outcomes)), outcomes], EPS, 1.0))


def brier_per_match(probs: np.ndarray, outcomes: np.ndarray) -> np.ndarray:
    """Multiclass Brier score: sum over classes of (p - y)^2. Range [0, 2]."""
    _check(probs, outcomes)
    return ((probs - one_hot(outcomes)) ** 2).sum(axis=1)


def rps_per_match(probs: np.ndarray, outcomes: np.ndarray) -> np.ndarray:
    """Ranked probability score (respects the H < D < A ordering). Range [0, 1]."""
    _check(probs, outcomes)
    cum_p = np.cumsum(probs, axis=1)[:, :2]
    cum_y = np.cumsum(one_hot(outcomes), axis=1)[:, :2]
    return ((cum_p - cum_y) ** 2).sum(axis=1) / 2.0


def accuracy_per_match(probs: np.ndarray, outcomes: np.ndarray) -> np.ndarray:
    _check(probs, outcomes)
    return (probs.argmax(axis=1) == outcomes).astype(float)


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    outcome: str
    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    observed_frequency: float | None


def calibration_bins(
    probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10
) -> list[CalibrationBin]:
    """Reliability table per outcome: mean predicted vs observed frequency per bin."""
    _check(probs, outcomes)
    y = one_hot(outcomes)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[CalibrationBin] = []
    for k, name in enumerate(OUTCOME_NAMES):
        p = probs[:, k]
        # right-inclusive last bin so p == 1.0 is counted
        idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
        for b in range(n_bins):
            mask = idx == b
            count = int(mask.sum())
            out.append(
                CalibrationBin(
                    outcome=name,
                    lower=float(edges[b]),
                    upper=float(edges[b + 1]),
                    count=count,
                    mean_predicted=float(p[mask].mean()) if count else None,
                    observed_frequency=float(y[mask, k].mean()) if count else None,
                )
            )
    return out


def expected_calibration_error(probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> float:
    """Count-weighted mean |predicted - observed| over all outcome bins."""
    bins = [b for b in calibration_bins(probs, outcomes, n_bins) if b.count]
    total = sum(b.count for b in bins)
    return float(
        sum(b.count * abs(b.mean_predicted - b.observed_frequency) for b in bins) / total  # type: ignore[operator]
    )


def bootstrap_mean_ci(
    values: np.ndarray, n_resamples: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean (deterministic seed)."""
    if len(values) == 0:
        raise ValueError("no values")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_resamples, len(values)))
    means = values[idx].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (well-behaved for small n)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
