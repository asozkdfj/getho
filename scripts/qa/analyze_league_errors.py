"""League heterogeneity diagnostics; no league selection or fitted policy."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from scripts.qa.analyze_draw_discrimination import confidence_summary, draw_summary
from scripts.qa.analyze_historical_errors import validate
from scripts.qa.analyze_paired_market import metrics, paired, winner


def group(rows):
    excess = [
        r for r in rows
        if max(r["production"]) - r["market"][winner(r["production"])] >= 0.1
    ]
    return {
        "n": len(rows),
        "production": metrics(rows, "production"), "market": metrics(rows, "market"),
        "paired": paired(rows, "production", "market"),
        "draw": draw_summary(rows), "excess_10pp": confidence_summary(excess),
    }


def analyze(rows):
    validate(rows)
    selected = [
        dict(r, market=r["market_only"], decision=r["kickoff_at"])
        for r in rows if r["season"] in ("2023-24", "2024-25", "2025-26")
    ]
    leagues = {
        league: group([r for r in selected if r["league"] == league])
        for league in sorted({r["league"] for r in selected})
    }
    cells = {
        league: {
            season: group([
                r for r in selected if r["league"] == league and r["season"] == season
            ])
            for season in sorted({r["season"] for r in selected if r["league"] == league})
        }
        for league in leagues
    }
    delta_key = "delta_log_loss_candidate_minus_baseline"
    return {
        "status": "EXPLORATORY_NO_LEAGUE_SELECTION",
        "n": len(selected),
        "by_league": leagues,
        "by_league_season": cells,
        "equal_league_weight_ll_delta": (
            sum(g["paired"][delta_key] for g in leagues.values()) / len(leagues)
            if leagues else None
        ),
        "fixture_weighted_ll_delta": (
            sum(g["n"] * g["paired"][delta_key] for g in leagues.values()) / len(selected)
            if selected else None
        ),
        "limitations": [
            "Same repeatedly explored 2023-26 artifact; no new holdout or training.",
            "Market availability time unknown; not same-decision evidence.",
            "Kickoff-week paired bootstrap 4000 draws, seed 20261019.",
            "Pointwise CIs are not multiplicity adjusted; not simultaneous significance.",
            "League heterogeneity is descriptive; no calibrated per-league model fitted.",
            "No actual Betman odds, ROI or causal explanation.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.predictions.read_bytes()
    result = analyze([json.loads(line) for line in gzip.decompress(raw).decode().splitlines()])
    result["predictions_sha256"] = hashlib.sha256(raw).hexdigest()
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for league, g in result["by_league"].items():
        print(league, json.dumps(g))


if __name__ == "__main__":
    main()
