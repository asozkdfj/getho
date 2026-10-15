"""Model promotion policy: a candidate replaces production only on evidence.

Decided on the TEST period of a backtest report (see experiments.py), where
'candidate' and 'production' were scored on the same matches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    min_matches: int = 300
    # A change must earn its complexity: either clearly better (paired 95% CI of the
    # log-loss difference entirely below 0) or better by at least this margin while
    # the CI upper bound stays below max_log_loss_ci_high.
    min_log_loss_gain: float = 0.002
    max_log_loss_ci_high: float = 0.005
    max_brier_diff: float = 0.0
    max_ece_increase: float = 0.01


@dataclass(slots=True)
class PromotionDecision:
    promote: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)


def decide(
    report: dict[str, Any],
    candidate: str = "candidate",
    production: str = "production",
    policy: PromotionPolicy | None = None,
) -> PromotionDecision:
    policy = policy or PromotionPolicy()
    models = report.get("models", {})
    if candidate not in models or production not in models:
        return PromotionDecision(False, [f"report lacks '{candidate}' or '{production}'"])
    cand, prod = models[candidate], models[production]
    vs = cand.get("vs_reference", {})
    if vs.get("reference") != production:
        return PromotionDecision(False, [f"paired comparison must use '{production}' as reference"])

    ll, br = vs["log_loss"], vs["brier"]
    checks = {
        "n_matches": report["n_matches"],
        "log_loss_diff": ll["mean_diff"],
        "log_loss_diff_ci": [ll["ci_low"], ll["ci_high"]],
        "brier_diff": br["mean_diff"],
        "ece_candidate": cand["ece"],
        "ece_production": prod["ece"],
    }
    reasons: list[str] = []
    if report["n_matches"] < policy.min_matches:
        reasons.append(f"too few test matches ({report['n_matches']} < {policy.min_matches})")
    significant = ll["ci_high"] < 0
    material = ll["mean_diff"] <= -policy.min_log_loss_gain
    if not (significant or material):
        reasons.append(
            f"log loss gain too small to matter ({ll['mean_diff']:+.4f}, "
            f"CI [{ll['ci_low']:+.4f}, {ll['ci_high']:+.4f}])"
        )
    if ll["ci_high"] > policy.max_log_loss_ci_high:
        reasons.append(f"log loss CI upper bound too high ({ll['ci_high']:+.4f})")
    if br["mean_diff"] > policy.max_brier_diff:
        reasons.append(f"Brier score worse ({br['mean_diff']:+.4f})")
    if cand["ece"] - prod["ece"] > policy.max_ece_increase:
        reasons.append(f"calibration worse (ECE {prod['ece']:.3f} -> {cand['ece']:.3f})")
    return PromotionDecision(not reasons, reasons or ["all promotion checks passed"], checks)
