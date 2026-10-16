"""`edge backtest-standings` - do league-table stakes (motivation proxies) help?

Pre-registered protocol (committed before the first run; do not edit after results):

Data     openfootball league files, 2018-19..2025-26. League table built only
         from results on earlier calendar days.
Leagues  9 of the 10 verified leagues, POOLED for the decision (one set of
         coefficients): en.1 en.2 de.1 de.2 es.1 it.1 fr.1 nl.1 pt.1.
         at.1 is excluded before running: its split format halves points
         mid-season, which a plain table cannot represent. EPL is also
         reported alone, for information only.
Variants dead_rubber          late season, cannot go down nor reach 6th
         relegation_pressure  closeness to the bottom-3 zone x season stage
         stakes               both
Timing   Production model refitted weekly, results enter training 3 h after
         kickoff (QA protocol). Coefficients refitted before each season on
         all earlier seasons of all 9 leagues.
Windows  2019-20 warm-up (first coefficients), 2020-21..2022-23 validation
         (choose one variant: lowest pooled log loss), 2023-24..2025-26
         follow-up (league results are complete for these seasons).
Gate     validation gain >= 0.001 AND follow-up gain >= 0.002 AND weekly
         paired 95% CI upper bound < 0 AND Brier not worse (pooled).
         Passing is a research result only: no automatic deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from edge_ingestion.feature_experiment import (
    Row,
    gate,
    production_rows,
    run_variants,
    write_predictions,
)
from edge_ingestion.history import openfootball
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams
from edge_ml.standings import VARIANTS, Standings

logger = logging.getLogger(__name__)

FIRST, LAST = "2018-19", "2025-26"
WARMUP = ["2019-20"]
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25", "2025-26"]
LEAGUES = "en.1,en.2,de.1,de.2,es.1,it.1,fr.1,nl.1,pt.1"


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default=LEAGUES, help="pooled for the decision")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--predictions-out", type=Path, help="write per-match predictions (JSONL)")


def _features(tables: dict[str, Standings], variant: str):
    fn = VARIANTS[variant]

    def build(rows: list[Row]) -> tuple[np.ndarray, np.ndarray]:
        x_h, x_a = [], []
        for r in rows:
            m = r.match.result
            t = tables[r.league]
            x_h.append(fn(t.stakes(m.home, m.season or "", m.kickoff_at)))
            x_a.append(fn(t.stakes(m.away, m.season or "", m.kickoff_at)))
        return np.asarray(x_h, dtype=float), np.asarray(x_a, dtype=float)

    return build


def _profile(rows: list[Row], tables: dict[str, Standings]) -> dict[str, Any]:
    st = [
        tables[r.league].stakes(team, r.match.result.season or "", r.match.result.kickoff_at)
        for r in rows
        for team in (r.match.result.home, r.match.result.away)
    ]
    n = len(st)
    return {
        "team_matches": n,
        "dead_rubber": sum(s.dead for s in st) / n,
        "pressure_gt_0_5": sum(s.pressure > 0.5 for s in st) / n,
        "mean_pressure": float(np.mean([s.pressure for s in st])),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    params = ModelParams()
    warnings: dict[str, list[str]] = {}
    rows: list[Row] = []
    tables: dict[str, Standings] = {}
    for code in codes:
        warnings[code] = []
        matches = openfootball.load(FIRST, LAST, args.cache_dir, code, warnings[code])
        tables[code] = Standings([m.result for m in matches])
        min_history = len([m for m in matches if m.result.season == FIRST])
        logger.info("standings backtest %s: %d matches", code, len(matches))
        rows += production_rows(
            code, matches, params, min_history, [WARMUP[0], VALIDATION[0], FOLLOW_UP[0]]
        )
    ex = run_variants(
        rows, {v: _features(tables, v) for v in VARIANTS}, [*VALIDATION, *FOLLOW_UP], params
    )
    if args.predictions_out:
        write_predictions(args.predictions_out, [ex])

    validation, follow_up = ex.segment(VALIDATION), ex.segment(FOLLOW_UP)
    seasons = openfootball.season_labels(FIRST, LAST)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "standings_stakes_v1",
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "protocol": __doc__,
        "leagues": codes,
        "variants": list(VARIANTS),
        "data_warnings": warnings,
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(args.cache_dir.glob("openfootball-*.json"))
            if any(f"-{c.replace('.', '')}-" in p.name for c in codes)
            and any(s in p.name for s in seasons)
        },
        "n_predicted": len(rows),
        "profile": _profile([r for r in rows if r.match.result.season != WARMUP[0]], tables),
        "coefficients": ex.coefficients,
        "validation": validation,
        "follow_up": follow_up,
        "per_league_follow_up": {c: ex.segment(FOLLOW_UP, league=c) for c in codes},
        "per_league_validation": {c: ex.segment(VALIDATION, league=c) for c in codes},
        "gate": gate(validation, follow_up, list(VARIANTS)),
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
