"""Shadow forecasts: recorded with the day's pick, from decision-time inputs only,
append-only, never affecting the pick (docs/experiments/shadow-forecasts-2026.md)."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from edge_api.db.models import DailyPick, OddsSnapshot, Prediction, ShadowForecast
from edge_api.services import picks as picks_module
from edge_api.services import queries
from edge_api.services import shadow as shadow_module
from edge_api.services.picks import publish_daily_pick
from edge_api.services.shadow import shadow_report
from edge_ml.market import devig
from tests.integration.test_picks import _pick_time, settings


def _rows(s):
    return s.scalars(select(ShadowForecast).order_by(ShadowForecast.fixture_id)).all()


def test_every_window_fixture_is_recorded_once_with_the_decision_inputs(
    session_factory, seeded, now
):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        rows = _rows(s)
        ld = picks_module.local_day(pick_now, settings())
        window = queries.fixtures_between(s, ld.start_utc, ld.end_utc, "mock")
        assert {r.fixture_id for r in rows} == {f.id for f in window}
        assert pick.evidence["shadow"] == {
            "protocol": "shadow-v1",
            "recorded": sum(r.status == "recorded" for r in rows),
            "excluded": sum(r.status == "excluded" for r in rows),
        }
        recorded = [r for r in rows if r.status == "recorded"]
        assert recorded
        for r in recorded:
            assert r.decided_at == pick_now and r.decision_date == pick.pick_date
            p = s.get(Prediction, r.prediction_id)
            assert r.forecasts["production"] == pytest.approx(
                [p.probability_home, p.probability_draw, p.probability_away]
            )
            o = s.get(OddsSnapshot, r.odds_snapshot_id)
            assert o.captured_at <= pick_now and o.created_at <= pick_now
            assert r.forecasts["market"] == pytest.approx(
                devig([float(o.odds_home), float(o.odds_draw), float(o.odds_away)])
            )
            assert r.build["code_fingerprint"]
        if pick.prediction_id is not None:  # the pick's own analysis is in the record
            chosen = next(r for r in rows if r.fixture_id == pick.fixture_id)
            assert chosen.prediction_id == pick.prediction_id
        for r in rows:
            if r.status == "excluded":
                assert r.excluded_reason and r.forecasts is None

        # a second decision the same day (re-request, replacement) adds nothing
        publish_daily_pick(s, settings(), pick_now + timedelta(minutes=5))
        publish_daily_pick(s, settings(), pick_now, revision=2)
        assert len(_rows(s)) == len(rows)


def test_started_matches_and_missing_predictions_are_excluded_with_a_reason(
    session_factory, seeded, now
):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        publish_daily_pick(s, settings(), pick_now)
        reasons = {r.excluded_reason for r in _rows(s) if r.status == "excluded"}
        assert reasons <= {
            "not_upcoming",
            "no_prediction",
            "prediction_after_decision",
            "no_market_odds",
            "stale_market_odds",
            "invalid_market_odds",
        }
        assert reasons, "the mock window has started or unpredicted fixtures"


def test_odds_seen_or_stored_after_the_decision_are_not_used(session_factory, seeded, now):
    from conftest import set_test_wall_clock

    with session_factory() as s:
        pick_now, fixture = _pick_time(s, now)
        base = queries.latest_predictions_by_fixture(s, [fixture.id])[fixture.id].odds_snapshot

        def add(captured, prices):
            s.add(
                OddsSnapshot(
                    fixture_id=fixture.id,
                    provider="mock",
                    bookmaker=base.bookmaker,
                    market="1X2",
                    captured_at=captured,
                    odds_home=prices[0],
                    odds_draw=prices[1],
                    odds_away=prices[2],
                    raw_payload={},
                )
            )
            s.flush()

        add(pick_now + timedelta(minutes=1), (9.0, 9.0, 1.1))  # captured later
        set_test_wall_clock(s, pick_now + timedelta(minutes=2))
        add(pick_now - timedelta(minutes=1), (1.2, 8.0, 15.0))  # captured before, stored later
        publish_daily_pick(s, settings(), pick_now)
        row = next(r for r in _rows(s) if r.fixture_id == fixture.id)
        assert row.status == "recorded" and row.odds_snapshot_id == base.id


def test_shadow_rows_are_append_only(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        publish_daily_pick(s, settings(), pick_now)
        s.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE shadow_forecasts SET status = 'excluded'"))
        s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM shadow_forecasts"))


def test_a_shadow_failure_never_blocks_the_pick(session_factory, seeded, now, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("shadow store unavailable")

    monkeypatch.setattr(picks_module, "record_shadow_forecasts", broken)
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        assert pick.id is not None and pick.evidence["shadow"]["error"].startswith("RuntimeError")
        assert _rows(s) == []
        assert s.scalars(select(DailyPick)).one().id == pick.id


def test_a_failing_shadow_lookup_never_blocks_the_pick(session_factory, seeded, now, monkeypatch):
    """Codex QA MORN-3: the shadow's own prediction lookup (fixtures outside the
    pick scope) fails; the pick is still published with the error recorded."""
    with session_factory() as s:
        decision, fixture = _pick_time(s, now)
        config = settings(pick_leagues=fixture.league.provider_id)
        original = queries.latest_predictions_by_fixture
        calls = []

        def fail_second(session, ids, as_of=None):
            calls.append(list(ids))
            if len(calls) == 2:
                assert ids and not set(ids) & set(calls[0])
                raise RuntimeError("shadow-only lookup failed")
            return original(session, ids, as_of=as_of)

        monkeypatch.setattr(queries, "latest_predictions_by_fixture", fail_second)
        pick = publish_daily_pick(s, config, decision)
        assert pick.id is not None
        assert pick.evidence["shadow"]["error"].startswith("RuntimeError")
        assert _rows(s) == []


def test_report_answers_nothing_before_final_and_accounts_for_every_day(
    session_factory, seeded, now, monkeypatch
):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        _settle_all(s, _rows(s))
        s.expire_all()
        day = pick.pick_date
        start = day - timedelta(days=2)
        report = shadow_report(s, "mock", now=now + timedelta(days=30), start=start, end=day)
        assert report["status"] == "provisional" and report["decisions"] == {}
        assert report["metrics"]["paired"]["blend_vs_market"]["weeks"] >= 1
        timing = report["decision_timing"]
        assert timing["days"] == 1
        expected = pick_now - picks_module.local_day(pick_now, settings()).publish_at
        assert timing["minutes_after_publish_hour"]["max"] == expected.total_seconds() / 60
        cov = report["coverage_days"]
        assert cov["days"] == 3 and cov["with_records"] == 1
        assert cov["no_decision"] == [start.isoformat(), (start + timedelta(days=1)).isoformat()]
        assert cov["shadow_failed"] == []


def _settle_all(s, rows):
    for i, r in enumerate(x for x in rows if x.status == "recorded"):
        s.execute(
            text(
                "UPDATE fixtures SET status='finished', home_score=:h, away_score=:a WHERE id=:id"
            ),
            {"h": i % 3, "a": 1, "id": r.fixture_id},
        )


def test_report_is_provisional_outside_the_pre_registered_window(session_factory, seeded, now):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        rows = _rows(s)
        _settle_all(s, rows)
        s.expire_all()
        report = shadow_report(
            s, "mock", now=now + timedelta(days=60), start=pick.pick_date, end=pick.pick_date
        )
        recorded = sum(r.status == "recorded" for r in rows)
        assert report["status"] == "provisional"
        assert report["settled"] == recorded == report["metrics"]["n"]
        assert sum(report["excluded"].values()) == len(rows) - recorded
        paired = report["metrics"]["paired"]["blend_vs_market"]
        assert paired["ci95_by_day"][0] <= paired["log_loss_diff"] <= paired["ci95_by_day"][1]


def test_report_is_final_only_for_the_complete_window_with_enough_matches(
    session_factory, seeded, now, monkeypatch
):
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        pick = publish_daily_pick(s, settings(), pick_now)
        _settle_all(s, _rows(s))
        s.expire_all()
        day = pick.pick_date
        monkeypatch.setattr(shadow_module, "EVALUATION_START", day)
        monkeypatch.setattr(shadow_module, "EVALUATION_END", day)
        args = {"start": day, "end": day}
        during = shadow_report(s, "mock", now=pick_now, **args)
        assert during["status"] == "provisional"  # window not over yet
        after = now + timedelta(days=30)
        assert shadow_report(s, "mock", now=after, **args)["status"] == "inconclusive"
        monkeypatch.setattr(shadow_module, "MIN_SETTLED", 1)
        final = shadow_report(s, "mock", now=after, **args)
        assert final["status"] == "final"
        assert set(final["decisions"]) == {
            "market_beats_production",
            "blend_beats_production",
            "blend_vs_market",
        }


def test_cli_prints_the_report(session_factory, seeded, now, monkeypatch, capsys):
    import json
    from contextlib import contextmanager

    from edge_ingestion import cli

    @contextmanager
    def scope():
        with session_factory() as s:
            yield s

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setenv("DATA_PROVIDER", "mock")
    from edge_api.config import get_settings

    get_settings.cache_clear()
    with session_factory() as s:
        pick_now, _ = _pick_time(s, now)
        publish_daily_pick(s, settings(), pick_now)
        s.commit()
        day = pick_now.date().isoformat()
    assert cli.main(["shadow-report", "--start", day, "--end", day]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["protocol"] == "shadow-v1" and report["status"] == "provisional"
    assert report["rows"] > 0
    get_settings.cache_clear()
