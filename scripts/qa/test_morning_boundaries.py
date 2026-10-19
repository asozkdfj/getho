"""Independent boundary probes for the October 19 morning changes."""

from datetime import timedelta

from sqlalchemy import select

from edge_api.db.models import Fixture, PlayerAppearance
from edge_api.services.team_news import regular_players
from edge_ingestion.providers.api_football import ApiFootballProvider


def test_late_player_row_in_known_fixture_is_not_a_historical_regular(db_session, seeded, now):
    fixture = db_session.scalars(select(Fixture).where(Fixture.kickoff_at < now).limit(1)).one()
    for pid, minutes, created_at in (
        ("qa-known", 10, now - timedelta(hours=1)),
        ("qa-future-star", 130, now + timedelta(hours=1)),
    ):
        db_session.add(
            PlayerAppearance(
                fixture_id=fixture.id,
                team_id=fixture.home_team_id,
                provider="mock",
                player_provider_id=pid,
                player_name=pid,
                started=True,
                minutes=minutes,
                created_at=created_at,
            )
        )
    db_session.flush()
    players, matches = regular_players(db_session, fixture.home_team_id, now, known_by=now)
    assert matches >= 1
    assert "qa-future-star" not in {pid for pid, _ in players}, players


def test_malformed_injury_report_must_not_be_called_covered(now, monkeypatch):
    provider = ApiFootballProvider("qa-not-a-real-key", reference_time=now, min_interval_seconds=0)
    monkeypatch.setattr(provider, "budget_ok", lambda: True)
    monkeypatch.setattr(
        provider,
        "_get",
        lambda *args, **kwargs: {
            "response": [
                {
                    "fixture": {"id": 123},
                    "team": {"id": 456},
                    "player": {"type": "Missing Fixture", "reason": "Injury"},
                }
            ]
        },
    )
    report = provider.get_absence_report({"123": now + timedelta(hours=1)})
    assert "123" not in report.covered, "Malformed injury became checked-and-empty"


def test_shadow_only_prediction_lookup_failure_does_not_block_pick(
    session_factory, seeded, now, monkeypatch
):
    from edge_api.services import queries
    from edge_api.services.picks import publish_daily_pick
    from tests.integration.test_picks import _pick_time, settings

    with session_factory() as session:
        decision, fixture = _pick_time(session, now)
        config = settings(pick_leagues=fixture.league.provider_id)
        original = queries.latest_predictions_by_fixture
        calls = []

        def fail_only_shadow(s, ids, as_of=None):
            calls.append(list(ids))
            if len(calls) == 2:
                assert ids, "probe requires fixtures outside the pick league"
                assert not set(ids) & set(calls[0])
                raise RuntimeError("QA: shadow-only lookup failed")
            return original(s, ids, as_of=as_of)

        monkeypatch.setattr(queries, "latest_predictions_by_fixture", fail_only_shadow)
        pick = publish_daily_pick(session, config, decision)
        assert pick.id is not None
        assert "error" in pick.evidence["shadow"]
