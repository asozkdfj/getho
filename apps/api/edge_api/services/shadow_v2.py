"""Shadow-v2: at the pick decision, record the shot-based form candidate next to
the production model and the market (docs/experiments/shadow-v2-2026.md).

Never shown, never changes the pick, append-only. The candidate uses only what
the decision could see: the same prediction (its stored expected goals) and
odds as shadow-v1, and post-match statistics stored by the decision for
league matches that kicked off at least 3 h before it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import Fixture, FixtureStatus, Prediction, ShadowForecast
from edge_api.services import queries
from edge_api.services.shadow import _exclusion, _outcome, market_odds_at
from edge_api.versioning import build_info
from edge_ml.metrics import cluster_bootstrap_ci
from edge_ml.shadow_v2 import (
    CANDIDATES,
    CI_SEED,
    EVALUATION_END,
    EVALUATION_START,
    MIN_GAIN,
    MIN_SETTLED,
    PROTOCOL,
    VARIANT,
    candidates,
)
from edge_ml.shots import MIN_MATCHES, RESULT_DELAY, ShotHistory

HISTORY_DAYS = 450  # enough for 10 matches per team and 300 league matches


def shot_histories(
    session: Session, provider: str, league_ids: set[int], at: datetime
) -> dict[int, ShotHistory]:
    """Per league: finished matches before ``at`` - 3 h whose statistics for both
    teams were stored by ``at``."""
    fixtures = session.scalars(
        select(Fixture).where(
            Fixture.provider == provider,
            Fixture.league_id.in_(league_ids),
            Fixture.status == FixtureStatus.FINISHED.value,
            Fixture.home_score.is_not(None),
            Fixture.away_score.is_not(None),
            Fixture.kickoff_at < at - RESULT_DELAY,
            Fixture.kickoff_at >= at - timedelta(days=HISTORY_DAYS),
        )
    ).all()
    stats: dict[int, dict[int, Any]] = defaultdict(dict)
    for s in queries.latest_statistics(session, [f.id for f in fixtures], as_of=at):
        stats[s.fixture_id][s.team_id] = s
    out: dict[int, ShotHistory] = {lid: ShotHistory() for lid in league_ids}
    for f in fixtures:
        h, a = stats[f.id].get(f.home_team_id), stats[f.id].get(f.away_team_id)
        if h is None or a is None or h.shots_on_target is None or a.shots_on_target is None:
            continue
        out[f.league_id].add(
            f.kickoff_at,
            str(f.home_team_id),
            str(f.away_team_id),
            f.home_score,
            f.away_score,
            float(h.shots_on_target),
            float(a.shots_on_target),
        )
    return {lid: h.freeze() for lid, h in out.items()}


def record_shadow_v2(
    session: Session,
    settings: Settings,
    *,
    decision_date: date,
    decided_at: datetime,
    fixtures: list[Fixture],
    in_scope: set[int],
    predictions: dict[int, Prediction],
) -> dict[str, int]:
    """One row per fixture of the window; idempotent per (day, protocol)."""
    odds = market_odds_at(session, [f.id for f in fixtures], settings.bookmaker, decided_at)
    hist = shot_histories(
        session, settings.data_provider, {f.league_id for f in fixtures}, decided_at
    )
    build = build_info()
    max_age = timedelta(hours=settings.odds_max_age)
    counts: Counter[str] = Counter()
    for f in fixtures:
        p, o = predictions.get(f.id), odds.get(f.id)
        reason = _exclusion(f, p, o, decided_at, max_age)
        h = hist[f.league_id]
        home, away = str(f.home_team_id), str(f.away_team_id)
        n_home, n_away = h.count(home, decided_at), h.count(away, decided_at)
        if reason is None and min(n_home, n_away) < MIN_MATCHES:
            reason = "insufficient_shot_history"
        forecasts = None
        if reason is None:
            assert p is not None and o is not None
            x_h = h.features(home, decided_at, VARIANT)
            x_a = h.features(away, decided_at, VARIANT)
            forecasts = {
                **candidates(
                    (p.probability_home, p.probability_draw, p.probability_away),
                    (float(o.odds_home), float(o.odds_draw), float(o.odds_away)),
                    (p.expected_goals_home, p.expected_goals_away),
                    x_h,
                    x_a,
                ),
                "inputs": {
                    "x_home": [round(float(v), 6) for v in x_h],
                    "x_away": [round(float(v), 6) for v in x_a],
                    "matches_home": n_home,
                    "matches_away": n_away,
                },
            }
        values: dict[str, Any] = {
            "provider": settings.data_provider,
            "protocol": PROTOCOL,
            "decision_date": decision_date,
            "decided_at": decided_at,
            "fixture_id": f.id,
            "kickoff_at": f.kickoff_at,
            "in_pick_scope": f.id in in_scope,
            "status": "recorded" if reason is None else "excluded",
            "excluded_reason": reason,
            "prediction_id": p.id if p is not None else None,
            "prediction_created_at": p.created_at if p is not None else None,
            "input_data_as_of": p.input_data_as_of if p is not None else None,
            "odds_snapshot_id": o.id if o is not None else None,
            "bookmaker": o.bookmaker if o is not None else None,
            "odds_captured_at": o.captured_at if o is not None else None,
            "odds_stored_at": o.created_at if o is not None else None,
            "forecasts": forecasts,
            "build": build,
        }
        inserted = session.execute(
            insert(ShadowForecast)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_shadow_forecasts_one_per_day")
            .returning(ShadowForecast.id)
        ).scalar_one_or_none()
        counts["recorded" if reason is None else "excluded"] += inserted is not None
    return dict(counts)


def shadow_v2_report(
    session: Session,
    provider: str,
    *,
    now: datetime,
    start: date = EVALUATION_START,
    end: date = EVALUATION_END,
) -> dict[str, Any]:
    rows = session.execute(
        select(ShadowForecast, Fixture)
        .join(Fixture, Fixture.id == ShadowForecast.fixture_id)
        .where(
            ShadowForecast.provider == provider,
            ShadowForecast.protocol == PROTOCOL,
            ShadowForecast.decision_date >= start,
            ShadowForecast.decision_date <= end,
        )
        .order_by(ShadowForecast.decision_date, ShadowForecast.id)
    ).all()
    excluded = Counter(r.excluded_reason for r, _ in rows if r.status == "excluded")
    settled, pending, not_played = [], 0, 0
    for r, f in rows:
        if r.status != "recorded":
            continue
        y = _outcome(f)
        if y is not None:
            settled.append((r, y))
        elif f.status in (FixtureStatus.POSTPONED.value, FixtureStatus.CANCELLED.value):
            not_played += 1
        else:
            pending += 1
    metrics = _metrics(settled)
    pre_registered = (start, end) == (EVALUATION_START, EVALUATION_END)
    complete = pending == 0 and now.date() > end
    if not (pre_registered and complete):
        status = "provisional"
    elif len(settled) < MIN_SETTLED:
        status = "inconclusive"
    else:
        status = "final"
    return {
        "protocol": PROTOCOL,
        "provider": provider,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": len(rows),
        "recorded": sum(1 for r, _ in rows if r.status == "recorded"),
        "excluded": dict(sorted(excluded.items())),
        "settled": len(settled),
        "pending": pending,
        "not_played": not_played,
        "min_settled": MIN_SETTLED,
        "status": status,
        "metrics": metrics,
        "decision": _decision(metrics) if status == "final" else {},
    }


def _metrics(settled: list[tuple[ShadowForecast, int]]) -> dict[str, Any]:
    if not settled:
        return {"n": 0}
    y = np.array([o for _, o in settled])
    probs = {k: np.array([r.forecasts[k] for r, _ in settled], dtype=float) for k in CANDIDATES}
    ll = {k: -np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)) for k, p in probs.items()}
    brier = {k: ((p - np.eye(3)[y]) ** 2).sum(axis=1) for k, p in probs.items()}
    days = [r.decision_date.isoformat() for r, _ in settled]
    weeks = [r.decision_date.isocalendar()[:2] for r, _ in settled]
    out: dict[str, Any] = {"n": len(y), "days": len(set(days))}
    for k in CANDIDATES:
        out[k] = {"log_loss": float(ll[k].mean()), "brier": float(brier[k].mean())}

    def paired(a: str, b: str) -> dict[str, Any]:
        diff = ll[a] - ll[b]  # negative: a is better
        lo, hi = cluster_bootstrap_ci(diff, days, seed=CI_SEED)
        wlo, whi = cluster_bootstrap_ci(diff, weeks, seed=CI_SEED)
        return {
            "log_loss_diff": float(diff.mean()),
            "ci95_by_day": [lo, hi],
            "ci95_by_week": [wlo, whi],
            "brier_diff": float((brier[a] - brier[b]).mean()),
        }

    out["paired"] = {
        "shots_vs_production": paired("production_shots_v1", "production"),
        "market_vs_shots": paired("market", "production_shots_v1"),
    }
    return out


def _decision(m: dict[str, Any]) -> dict[str, Any]:
    d = m["paired"]["shots_vs_production"]
    checks = {
        "gain>=0.002": -d["log_loss_diff"] >= MIN_GAIN,
        "ci95_by_day_upper<0": d["ci95_by_day"][1] < 0,
        "brier_not_worse": d["brier_diff"] <= 0,
    }
    return {
        "checks": checks,
        "forward_test_passed": all(checks.values()),
        "deployed": False,
        "next": "model 0.3.0 needs Codex QA and the user's approval",
    }
