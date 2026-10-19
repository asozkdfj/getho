"""Live CLV: from the decision-time price stored with each shadow forecast to the
bookmaker's last snapshot before kickoff (services/live_clv.py)."""

from datetime import timedelta

import numpy as np
import pytest
from sqlalchemy import select

from edge_api.db.models import Fixture, OddsSnapshot, ShadowForecast
from edge_api.services.live_clv import live_clv_report
from edge_api.services.picks import publish_daily_pick
from edge_ml.clv import partial_slope, plain_slope
from tests.integration.test_picks import _pick_time, settings


def _decide(s, now):
    pick_now, _ = _pick_time(s, now)
    pick = publish_daily_pick(s, settings(), pick_now)
    rows = s.scalars(select(ShadowForecast).where(ShadowForecast.status == "recorded")).all()
    assert rows
    return pick, rows


def _snapshot(s, r, captured, fair):
    early = s.get(OddsSnapshot, r.odds_snapshot_id)
    odds = [round(1 / p, 4) for p in fair]
    s.add(
        OddsSnapshot(
            fixture_id=r.fixture_id,
            provider="mock",
            bookmaker=early.bookmaker,
            market="1X2",
            captured_at=captured,
            odds_home=odds[0],
            odds_draw=odds[1],
            odds_away=odds[2],
            raw_payload={},
        )
    )


def _report(s, pick, rows, **kw):
    kickoffs = [s.get(Fixture, r.fixture_id).kickoff_at for r in rows]
    return live_clv_report(
        s,
        "mock",
        now=kw.pop("now", max(kickoffs) + timedelta(hours=3)),
        start=pick.pick_date,
        end=pick.pick_date,
    )


def test_market_moving_halfway_to_the_model_reads_one_half(session_factory, seeded, now):
    with session_factory() as s:
        pick, rows = _decide(s, now)
        for r in rows:
            f = s.get(Fixture, r.fixture_id)
            model, early = np.array(r.forecasts["production"]), np.array(r.forecasts["market"])
            _snapshot(s, r, f.kickoff_at - timedelta(minutes=30), early + 0.5 * (model - early))
            # after kickoff: in-play prices are never the close
            _snapshot(s, r, f.kickoff_at + timedelta(minutes=5), (0.9, 0.05, 0.05))
        s.flush()
        report = _report(s, pick, rows)
        assert report["counts"]["analysed"] == len(rows)
        partial = report["all"]["partial_by_day"]
        assert partial["b_forecast"] == pytest.approx(0.5, abs=1e-3)
        assert partial["b_base"] == pytest.approx(0.0, abs=1e-3)
        assert report["all"]["share_moves_toward_model"] == pytest.approx(1.0)
        assert report["all"]["closing_snapshot_minutes_before_kickoff"]["median"] == 30
        assert report["reading"]["decision"] == "none (monitoring)"
        flags = {f["threshold"]: f for f in report["all"]["large_gap_clv"]}
        assert all(f["mean_clv"] is None or f["mean_clv"] > -0.2 for f in flags.values())


def test_without_a_later_snapshot_or_before_kickoff_nothing_is_scored(session_factory, seeded, now):
    with session_factory() as s:
        pick, rows = _decide(s, now)
        first_kickoff = min(s.get(Fixture, r.fixture_id).kickoff_at for r in rows)
        early_report = _report(s, pick, rows, now=first_kickoff - timedelta(minutes=1))
        assert early_report["counts"]["before_kickoff"] == len(rows)
        assert early_report["all"] == {"n": 0}
        late = _report(s, pick, rows)
        assert late["counts"]["no_later_snapshot"] == len(rows)  # only the decision price exists
        assert late["counts"].get("analysed", 0) == 0


def test_results_of_the_evaluated_fixtures_are_never_read(session_factory, seeded, now):
    with session_factory() as s:
        pick, rows = _decide(s, now)
        for r in rows:
            f = s.get(Fixture, r.fixture_id)
            model, early = np.array(r.forecasts["production"]), np.array(r.forecasts["market"])
            _snapshot(s, r, f.kickoff_at - timedelta(minutes=10), early + 0.3 * (model - early))
        s.flush()
        before = _report(s, pick, rows)
        for i, r in enumerate(rows):
            f = s.get(Fixture, r.fixture_id)
            f.status, f.home_score, f.away_score = "finished", i % 3, 1
        s.flush()
        after = _report(s, pick, rows)
        assert before["all"] == after["all"]


def test_partial_slope_does_not_credit_a_no_information_forecast():
    rng = np.random.default_rng(3)
    n = 4000
    base = np.tile([0.45, 0.27, 0.28], (n, 1))
    truth = 0.6 * base + 0.4 * rng.dirichlet([4, 3, 3], size=n)
    noise = rng.normal(0, 0.04, size=(n, 3))
    early = truth + noise - noise.mean(axis=1, keepdims=True)
    junk = rng.normal(0, 0.04, size=(n, 3))
    model = base + junk - junk.mean(axis=1, keepdims=True)
    days = np.arange(n) // 20
    assert plain_slope(model, early, truth, days, 1)["beta"] > 0.1
    partial = partial_slope(model, base, early, truth, days, 1)
    assert partial["b_forecast_ci95"][0] < 0 < partial["b_forecast_ci95"][1]
