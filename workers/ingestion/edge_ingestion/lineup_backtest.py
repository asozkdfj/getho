"""`edge backtest-lineups` - does line-up strength improve the model? (stage 2)

Sources:
  statsbomb  StatsBomb open data, complete 2015/16 seasons with line-ups and minutes
  db         this database: finished fixtures + player_appearances collected from the
             provider (fill them first with `edge backfill-appearances`)
Per league, matches are split by time:
  warm-up     the first 26% (history only)
  validation  up to 60%: fit beta/gamma (line-up adjustment), nothing else
  test        the rest, scored once with everything frozen
Test predictions of all leagues are pooled and judged with the same promotion
policy as any other model change.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from edge_ml.backtest import BacktestConfig, Predictions, evaluate, walk_forward
from edge_ml.forecasters import BacktestMatch, BaseRateForecaster, ModelForecaster
from edge_ml.lineups import LineupForecaster, LineupIndex, collect_offsets, fit_coefficients
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams
from edge_ml.promotion import decide

logger = logging.getLogger(__name__)

WARMUP_SHARE, VALIDATION_END_SHARE = 0.26, 0.60  # 100 / 230 of a 380-match season
# The verdict must not hinge on one split point: the change is adopted only if the
# promotion policy passes for every validation end below (decided before running).
SENSITIVITY_SHARES = (0.55, 0.60, 0.65)
MIN_LEAGUE_MATCHES = 200


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--source", choices=["statsbomb", "db"], default="statsbomb")
    p.add_argument(
        "--leagues",
        default="en.1,es.1,it.1,fr.1",
        help="StatsBomb league codes (source=statsbomb)",
    )
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the full JSON report here")


def _merge(parts: list[Predictions]) -> Predictions:
    out = Predictions(matches=[m for p in parts for m in p.matches])
    for name in parts[0].probs:
        out.probs[name] = np.concatenate([p.probs[name] for p in parts])
        out.skipped[name] = sum(p.skipped.get(name, 0) for p in parts)
    return out


def _split(
    matches: list[BacktestMatch], validation_end: float = VALIDATION_END_SHARE
) -> tuple[datetime, datetime, int]:
    ordered = sorted(m.result.kickoff_at for m in matches)
    warmup = int(len(ordered) * WARMUP_SHARE)
    return ordered[warmup], ordered[int(len(ordered) * validation_end)], warmup


def evaluate_split(
    data: dict[str, list[BacktestMatch]],
    names: dict[str, str],
    production: ModelParams,
    validation_end: float,
) -> dict[str, Any]:
    """Fit the line-up adjustment on validation, then score the frozen test period."""
    rows = []
    for matches in data.values():
        val_start, test_start, warmup = _split(matches, validation_end)
        rows.append(collect_offsets(matches, production, val_start, test_start, min_history=warmup))
    fit = fit_coefficients(np.concatenate(rows))
    parts, per_league = [], {}
    for code, matches in data.items():
        _, test_start, warmup = _split(matches, validation_end)
        cfg = BacktestConfig(eval_start=test_start, min_history=warmup, reference="production")
        forecasters = [
            BaseRateForecaster(),
            ModelForecaster("production", production),
            LineupForecaster(
                "production_lineup",
                production,
                LineupIndex.build(matches),
                beta=fit.beta,
                gamma=fit.gamma,
            ),
        ]
        preds = walk_forward(matches, forecasters, cfg)
        parts.append(preds)
        ev = evaluate(preds, cfg)
        per_league[code] = {
            "name": names[code],
            "test_matches": ev["n_matches"],
            "log_loss": {n: m["log_loss"]["mean"] for n, m in ev["models"].items()},
        }
    first = min(m.result.kickoff_at for p in parts for m in p.matches)
    pooled = evaluate(_merge(parts), BacktestConfig(eval_start=first, reference="production"))
    return {
        "validation_end": validation_end,
        "fit": dataclasses.asdict(fit),
        "test": pooled,
        "per_league": per_league,
        "promotion": dataclasses.asdict(decide(pooled, candidate="production_lineup")),
    }


def load_db_matches(
    s: Any, provider: str, min_matches: int = MIN_LEAGUE_MATCHES
) -> tuple[dict[str, list[BacktestMatch]], dict[str, str]]:
    """Finished fixtures with player minutes for both teams, per league."""
    from collections import defaultdict

    from sqlalchemy import select

    from edge_api.db.models import Fixture, League, PlayerAppearance
    from edge_ml.core import MatchResult
    from edge_ml.forecasters import MatchLineups, TeamSheet

    data: dict[str, list[BacktestMatch]] = defaultdict(list)
    names: dict[str, str] = {}
    apps = defaultdict(lambda: defaultdict(lambda: ([], {})))
    for a in s.scalars(select(PlayerAppearance).where(PlayerAppearance.provider == provider)):
        starters, minutes = apps[a.fixture_id][a.team_id]
        if a.started:
            starters.append(a.player_provider_id)
        minutes[a.player_provider_id] = a.minutes
    fixtures = s.scalars(
        select(Fixture)
        .join(League, League.id == Fixture.league_id)
        .where(Fixture.id.in_(list(apps)), Fixture.status == "finished")
    ).unique()
    for f in fixtures:
        sheets = apps[f.id]
        home, away = sheets.get(f.home_team_id), sheets.get(f.away_team_id)
        if not home or not away or len(home[0]) != 11 or len(away[0]) != 11:
            continue
        key = f"{f.league.provider_id}"
        names[key] = f"{f.league.country} - {f.league.name}"
        data[key].append(
            BacktestMatch(
                MatchResult(
                    str(f.home_team_id),
                    str(f.away_team_id),
                    f.home_score,
                    f.away_score,
                    f.kickoff_at,
                    f.season,
                ),
                lineups=MatchLineups(
                    TeamSheet(tuple(home[0]), dict(home[1])),
                    TeamSheet(tuple(away[0]), dict(away[1])),
                ),
            )
        )
    keep = {k: v for k, v in data.items() if len(v) >= min_matches}
    return keep, names


def run(args: argparse.Namespace) -> dict[str, Any]:
    production = ModelParams()
    if getattr(args, "source", "statsbomb") == "db":
        from edge_api.config import get_settings
        from edge_api.db.session import session_scope

        with session_scope() as session:
            data, names = load_db_matches(session, get_settings().data_provider)
        source = {"name": "database (provider player minutes)", "license": "see provider terms"}
        seasons = {c: sorted({m.result.season or "?" for m in ms}) for c, ms in data.items()}
        if not data:
            raise SystemExit(
                f"no league has {MIN_LEAGUE_MATCHES}+ finished fixtures with player minutes; "
                "run `edge backfill-appearances` first"
            )
    else:
        from edge_ingestion.history import statsbomb

        codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
        data = {code: statsbomb.load(code, args.cache_dir) for code in codes}
        names = {c: statsbomb.SEASONS[c].name for c in codes}
        source = {
            "name": "StatsBomb open data",
            "license": "free for research; credit StatsBomb when publishing",
        }
        seasons = {c: [statsbomb.SEASONS[c].season] for c in codes}

    main = evaluate_split(data, names, production, VALIDATION_END_SHARE)
    sensitivity = []
    for share in SENSITIVITY_SHARES:
        res = (
            main
            if share == VALIDATION_END_SHARE
            else evaluate_split(data, names, production, share)
        )
        checks = res["promotion"]["checks"]
        sensitivity.append(
            {
                "validation_end": share,
                "beta": res["fit"]["beta"],
                "gamma": res["fit"]["gamma"],
                "test_matches": checks.get("n_matches"),
                "log_loss_diff": checks.get("log_loss_diff"),
                "log_loss_diff_ci": checks.get("log_loss_diff_ci"),
                "promote": res["promotion"]["promote"],
            }
        )
    robust = all(row["promote"] for row in sensitivity)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "data": {
            **source,
            "seasons": seasons,
            "n_matches": {c: len(m) for c, m in data.items()},
        },
        "split": {
            "warmup": f"first {WARMUP_SHARE:.0%} of each league's matches",
            "validation": f"up to {VALIDATION_END_SHARE:.0%} (fit beta, gamma only)",
            "test": "the rest, scored once, pooled over leagues",
        },
        "production": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "lineup_fit": main["fit"],
        "test": main["test"],
        "per_league": main["per_league"],
        "promotion": main["promotion"],
        "sensitivity": sensitivity,
        "adopt": robust,
        "adopt_rule": "promotion policy must pass for every validation end in "
        f"{list(SENSITIVITY_SHARES)}",
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return report
