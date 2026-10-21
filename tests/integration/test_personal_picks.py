"""The user's own picks, stage R1: storage, revisions, record type and the frozen
pre-match analysis (docs/qa/2026-10-21-personal-pick-review-spec.md)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.config import Settings
from edge_api.db.models import Fixture, OddsSnapshot, PersonalPick, Prediction
from edge_api.schemas import PersonalPickIn, PersonalPickRevisionIn
from edge_api.services import personal_picks
from edge_api.services.personal_picks import PickConflictError, PickError

SETTINGS = Settings(data_provider="mock")
CTX = {"bookmaker": SETTINGS.bookmaker, "provider": "mock"}


def _upcoming_with_prediction(s, now, top="HOME"):
    """An upcoming fixture whose stored prediction favours ``top``."""
    preds = s.scalars(
        select(Prediction)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .where(Fixture.status == "scheduled", Fixture.kickoff_at > now + timedelta(hours=6))
        .order_by(Fixture.kickoff_at, Fixture.id)
    ).all()
    for p in preds:
        probs = {"HOME": p.probability_home, "DRAW": p.probability_draw, "AWAY": p.probability_away}
        if max(probs, key=probs.__getitem__) == top:
            return p.fixture, p
    raise AssertionError(f"no upcoming fixture favouring {top}")


def _finished(s, now):
    return s.scalars(
        select(Fixture)
        .where(Fixture.status == "finished", Fixture.kickoff_at < now - timedelta(days=1))
        .order_by(Fixture.kickoff_at.desc())
        .limit(1)
    ).one()


def _body(fixture_id, key="key-0001", **kw):
    return {"idempotency_key": key, "fixture_id": fixture_id, "selection": "AWAY", **kw}


def _count(s):
    return s.scalar(select(func.count()).select_from(PersonalPick))


# ------------------------------------------------------------------ analysis


def test_away_pick_is_analysed_with_the_away_probability(client, session_factory, now):
    """QA 1: user picks away, the model favours home."""
    with session_factory() as s:
        fixture, pred = _upcoming_with_prediction(s, now, top="HOME")
    res = client.post("/personal-picks", json=_body(fixture.id, entry_odds=3.4))
    assert res.status_code == 200, res.text
    pick = res.json()
    a = pick["current"]["analysis"]
    m = a["model"]
    assert m["prediction_id"] == pred.id
    assert m["selection_probability"] == pytest.approx(pred.probability_away)
    assert m["failure_probability"] == pytest.approx(1 - pred.probability_away)
    assert {o["outcome"]: o["probability"] for o in m["failure_outcomes"]} == pytest.approx(
        {"HOME": pred.probability_home, "DRAW": pred.probability_draw}
    )
    assert m["top_outcome"] == "HOME" and m["agrees_with_top"] is False
    assert "selection_differs_from_model_top" in a["warnings"]
    # break-even and the model-assumption estimate use the entered price
    assert a["price"]["break_even_probability"] == pytest.approx(1 / 3.4)
    assert a["price"]["model_assumption_return"] == pytest.approx(pred.probability_away * 3.4 - 1)
    # same-time market for the same result
    mk = a["market"]
    assert mk["selection_fair_probability"] == pytest.approx(mk["fair_probabilities"]["away"])
    assert mk["model_minus_market"] == pytest.approx(
        pred.probability_away - mk["selection_fair_probability"]
    )
    assert pick["current"]["source_type"] == "prospective_record"
    assert pick["prospective_revision"] == 1 and pick["edited_after_kickoff"] is False


def test_missing_inputs_are_reported_not_filled(client, session_factory, now):
    """QA 4: no entry odds / own probability -> missing, never 0 or the model's value."""
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
    cur = client.post("/personal-picks", json=_body(fixture.id)).json()["current"]
    a = cur["analysis"]
    assert cur["entry_odds"] is None and cur["user_probability"] is None
    assert a["price"] is None
    missing = {m["item"]: m["reason"] for m in a["missing"]}
    assert missing["entry_odds"] == "not_entered"
    assert missing["user_probability"] == "not_entered"
    # absences never collected on this run: unknown, not "no absences"
    assert a["team_news"]["home"]["absences_status"] == "unknown"
    assert missing["absences_home"] == "not_checked"
    assert "absences_unknown_home" in a["warnings"]
    assert "league_not_verified" in a["warnings"]  # synthetic leagues are never verified


def test_frozen_analysis_ignores_later_predictions_and_odds(client, session_factory, now):
    """QA 2: a prediction or odds stored after the pick never change its analysis."""
    from conftest import set_test_wall_clock

    with session_factory() as s:
        fixture, pred = _upcoming_with_prediction(s, now)
    first = client.post("/personal-picks", json=_body(fixture.id)).json()
    with session_factory() as s:
        set_test_wall_clock(s, now + timedelta(hours=1))
        later_odds = OddsSnapshot(
            fixture_id=fixture.id,
            provider="mock",
            bookmaker=SETTINGS.bookmaker,
            market="1X2",
            captured_at=now + timedelta(hours=1),
            odds_home=Decimal("1.50"),
            odds_draw=Decimal("4.00"),
            odds_away=Decimal("7.00"),
        )
        s.add(later_odds)
        s.flush()
        s.add(
            Prediction(
                fixture_id=fixture.id,
                model_version_id=pred.model_version_id,
                market_odds_snapshot_id=later_odds.id,
                input_data_as_of=now + timedelta(hours=1),
                probability_home=0.7,
                probability_draw=0.2,
                probability_away=0.1,
                expected_goals_home=2.0,
                expected_goals_away=0.6,
                features={},
            )
        )
        s.commit()
    again = client.get(f"/personal-picks/{first['pick_id']}").json()
    assert again["current"]["analysis"] == first["current"]["analysis"]

    # a revision stored later is analysed as of its own decision time
    with session_factory() as s:
        out = personal_picks.revise_pick(
            s,
            first["pick_id"],
            PersonalPickRevisionIn(idempotency_key="rev-0001", base_revision=1, selection="AWAY"),
            now=now + timedelta(hours=2),
            **CTX,
        )
    assert out.current.analysis.model is not None
    assert out.current.analysis.model.selection_probability == pytest.approx(0.1)
    assert out.history[0].analysis.model.prediction_id == pred.id  # first revision untouched


def test_decision_before_the_prediction_existed_has_no_model_view(client, session_factory, now):
    """A past decision time sees only rows stored by then (here: nothing yet)."""
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
    early = (now - timedelta(hours=3)).isoformat()
    a = client.post("/personal-picks", json=_body(fixture.id, decision_at=early)).json()
    analysis = a["current"]["analysis"]
    assert analysis["model"] is None and analysis["market"] is None
    reasons = {m["item"]: m["reason"] for m in analysis["missing"]}
    assert reasons["model"] == "no_prediction_known_at_decision"
    assert reasons["market"] == "no_odds_known_at_decision"
    assert a["current"]["time_evidence"] == "user_stated"
    assert a["current"]["source_type"] == "prospective_record"  # stored before kickoff


# ------------------------------------------------------------------ record type


def test_pick_entered_after_kickoff_is_retrospective(client, session_factory, now):
    """QA 3/9: a pick entered after the match never counts as a pre-match record."""
    with session_factory() as s:
        fixture = _finished(s, now)
    decided = (fixture.kickoff_at - timedelta(hours=2)).isoformat()
    res = client.post("/personal-picks", json=_body(fixture.id, decision_at=decided))
    assert res.status_code == 200, res.text
    pick = res.json()
    assert pick["current"]["source_type"] == "retrospective_self_report"
    assert pick["prospective_revision"] is None
    listing = client.get("/personal-picks").json()
    assert listing["counts"] == {"prospective_record": 0, "retrospective_self_report": 1}

    # without a decision time the server clock is after kickoff: refused
    res = client.post("/personal-picks", json=_body(fixture.id, key="key-0002"))
    assert res.status_code == 422


def test_correction_after_kickoff_is_marked_retrospective(session_factory, seeded, now):
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
        first = personal_picks.create_pick(
            s,
            PersonalPickIn(idempotency_key="key-0001", fixture_id=fixture.id, selection="HOME"),
            now=now,
            **CTX,
        )
        later = fixture.kickoff_at + timedelta(hours=3)
        with pytest.raises(PickError):  # server clock after kickoff
            personal_picks.revise_pick(
                s,
                first.pick_id,
                PersonalPickRevisionIn(
                    idempotency_key="rev-0001", base_revision=1, selection="DRAW"
                ),
                now=later,
                **CTX,
            )
        s.rollback()
        out = personal_picks.revise_pick(
            s,
            first.pick_id,
            PersonalPickRevisionIn(
                idempotency_key="rev-0002",
                base_revision=1,
                selection="DRAW",
                decision_at=fixture.kickoff_at - timedelta(minutes=30),
            ),
            now=later,
            **CTX,
        )
    assert out.current.selection == "DRAW"
    assert out.current.source_type == "retrospective_self_report"
    assert out.prospective_revision == 1 and out.edited_after_kickoff is True
    assert [r.selection for r in out.history] == ["HOME", "DRAW"]


# ------------------------------------------------------------------ safety


def test_same_request_twice_stores_one_pick(client, session_factory, now):
    """QA 6: a retried request is not a second pick; a reused key with another body is."""
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
    a = client.post("/personal-picks", json=_body(fixture.id, stake_krw=5000)).json()
    b = client.post("/personal-picks", json=_body(fixture.id, stake_krw=5000)).json()
    assert a == b
    conflict = client.post("/personal-picks", json=_body(fixture.id, stake_krw=9000))
    assert conflict.status_code == 409
    with session_factory() as s:
        assert _count(s) == 1


def test_stale_revision_is_refused(client, session_factory, now):
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
    pick = client.post("/personal-picks", json=_body(fixture.id)).json()
    url = f"/personal-picks/{pick['pick_id']}/revisions"
    ok = client.post(
        url, json={"idempotency_key": "rev-0001", "base_revision": 1, "selection": "HOME"}
    )
    assert ok.status_code == 200 and ok.json()["revisions"] == 2
    stale = client.post(
        url, json={"idempotency_key": "rev-0002", "base_revision": 1, "selection": "DRAW"}
    )
    assert stale.status_code == 409
    replay = client.post(
        url, json={"idempotency_key": "rev-0001", "base_revision": 1, "selection": "HOME"}
    )
    assert replay.status_code == 200 and replay.json()["revisions"] == 2


def test_invalid_requests_are_refused(client, session_factory, now):
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)

    def status(**kw):
        return client.post("/personal-picks", json=_body(fixture.id, **kw)).status_code

    assert status(decision_at=(now + timedelta(minutes=5)).isoformat()) == 422  # future
    assert status(decision_at=now.replace(tzinfo=None).isoformat()) == 422  # no time zone
    assert status(entry_odds=1.0) == 422
    assert status(entry_odds=2.155) == 422  # would be rounded by NUMERIC(8, 2)
    assert status(user_probability=1) == 422
    assert client.post("/personal-picks", json=_body(999_999)).status_code == 404
    assert client.get("/personal-picks/not-a-pick").status_code == 404
    with session_factory() as s:
        assert _count(s) == 0


def test_reason_is_kept_as_plain_text(client, session_factory, now):
    """QA 12 (server side): markup is stored as text; control characters dropped.
    The page renders it escaped (apps/web tests)."""
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
    reason = "<script>alert(1)</script>\x00 홈 수비 불안"
    cur = client.post("/personal-picks", json=_body(fixture.id, user_reason=reason)).json()
    assert cur["current"]["user_reason"] == "<script>alert(1)</script> 홈 수비 불안"


def test_personal_picks_are_append_only(client, session_factory, now):
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
    client.post("/personal-picks", json=_body(fixture.id))
    with session_factory() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE personal_picks SET selection = 'HOME'"))
        s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM personal_picks"))
        s.rollback()


def test_concurrent_duplicate_resolves_to_the_stored_pick(
    session_factory, seeded, now, monkeypatch
):
    """Two requests with the same key racing: the second one's lookup ran before
    the first committed, so its insert hits the unique key; it must return the
    first pick instead of failing or storing a second row."""
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
    request = PersonalPickIn(idempotency_key="key-0001", fixture_id=fixture.id, selection="HOME")
    with session_factory() as a:
        first = personal_picks.create_pick(a, request, now=now, **CTX)

    real = personal_picks._replay
    calls = []

    def racing(session, key, sha):
        calls.append(key)
        return None if len(calls) == 1 else real(session, key, sha)

    monkeypatch.setattr(personal_picks, "_replay", racing)
    with session_factory() as b:
        second = personal_picks.create_pick(b, request, now=now, **CTX)
    assert len(calls) == 2  # the lookup after the failed insert found the stored pick
    assert first.pick_id == second.pick_id
    with session_factory() as s:
        assert _count(s) == 1


def test_stale_revision_raises_in_the_service(session_factory, seeded, now):
    with session_factory() as s:
        fixture, _ = _upcoming_with_prediction(s, now)
        first = personal_picks.create_pick(
            s,
            PersonalPickIn(idempotency_key="key-0001", fixture_id=fixture.id, selection="HOME"),
            now=now,
            **CTX,
        )
        with pytest.raises(PickConflictError):
            personal_picks.revise_pick(
                s,
                first.pick_id,
                PersonalPickRevisionIn(
                    idempotency_key="rev-0001", base_revision=2, selection="DRAW"
                ),
                now=now,
                **CTX,
            )


def _late_prediction(s, fixture, pred, *, inputs_as_of, stored_at):
    from conftest import set_test_wall_clock

    set_test_wall_clock(s, stored_at)
    late = Prediction(
        fixture_id=fixture.id,
        model_version_id=pred.model_version_id,
        market_odds_snapshot_id=pred.market_odds_snapshot_id,
        input_data_as_of=inputs_as_of,
        probability_home=0.7,
        probability_draw=0.2,
        probability_away=0.1,
        expected_goals_home=2.0,
        expected_goals_away=0.6,
        features={},
    )
    s.add(late)
    s.commit()
    return late


def test_prediction_stored_after_the_decision_is_not_used(session_factory, seeded, now):
    """Built from old inputs but stored after the decision: not known at it."""
    with session_factory() as s:
        fixture, pred = _upcoming_with_prediction(s, now)
        late = _late_prediction(
            s,
            fixture,
            pred,
            inputs_as_of=now - timedelta(hours=1),
            stored_at=now + timedelta(hours=1),
        )
        out = personal_picks.create_pick(
            s,
            PersonalPickIn(
                idempotency_key="key-0001",
                fixture_id=fixture.id,
                selection="AWAY",
                decision_at=now + timedelta(minutes=30),
            ),
            now=now + timedelta(hours=2),
            **CTX,
        )
    model = out.current.analysis.model
    assert model is not None and model.prediction_id == pred.id != late.id


def test_absences_stored_after_the_pick_do_not_change_it(client, session_factory, now):
    """QA 2 (team news): absences collected later leave the stored analysis as it was."""
    from conftest import set_test_wall_clock
    from edge_ingestion.providers import MockProvider
    from edge_ingestion.providers.mock import ABSENCES_KNOWN
    from edge_ingestion.team_news import ingest_team_news

    news = Settings(data_provider="mock", team_news_leagues="all", absences_horizon_hours=24 * 5)
    with session_factory() as s:
        fixture = s.scalars(
            select(Fixture)
            .join(Prediction, Prediction.fixture_id == Fixture.id)
            .where(Fixture.status == "scheduled", Fixture.kickoff_at > now)
            .where(Fixture.kickoff_at <= now + ABSENCES_KNOWN)
            .order_by(Fixture.kickoff_at)
            .limit(1)
        ).one()
    first = client.post("/personal-picks", json=_body(fixture.id)).json()
    with session_factory() as s:
        set_test_wall_clock(s, now + timedelta(minutes=10))
        ingest_team_news(s, MockProvider(now), now=now, settings=news)
        s.commit()
    again = client.get(f"/personal-picks/{first['pick_id']}").json()
    assert again["current"]["analysis"] == first["current"]["analysis"]
    assert again["current"]["analysis"]["team_news"]["home"]["absences_status"] == "unknown"
    with session_factory() as s:
        out = personal_picks.revise_pick(
            s,
            first["pick_id"],
            PersonalPickRevisionIn(idempotency_key="rev-0001", base_revision=1, selection="AWAY"),
            now=now + timedelta(minutes=20),
            **CTX,
        )
    side = out.current.analysis.team_news.home
    assert side.absences_status in {"reported", "none_reported"}
    assert out.current.analysis.team_news.snapshot_ids
