"""Player information as known at a moment: absences state, as_of reads and the
09:00 coverage report (ADR-026)."""

from datetime import datetime, timedelta

from sqlalchemy import select

from edge_api.config import Settings
from edge_api.db.models import Fixture
from edge_api.services.team_news import team_news
from edge_api.services.team_news_coverage import coverage_on
from edge_ingestion.providers import MockProvider
from edge_ingestion.providers.mock import ABSENCES_KNOWN
from edge_ingestion.team_news import ingest_team_news

NEWS = Settings(data_provider="mock", team_news_leagues="all", absences_horizon_hours=24 * 5)


def _news(session, now):
    ingest_team_news(session, MockProvider(now), now=now, settings=NEWS)
    session.flush()


def _upcoming(session, now, after, before):
    return session.scalars(
        select(Fixture)
        .where(
            Fixture.status == "scheduled",
            Fixture.kickoff_at > now + after,
            Fixture.kickoff_at <= now + before,
        )
        .order_by(Fixture.kickoff_at)
    ).all()


def test_api_tells_checked_none_from_not_checked(client, session_factory, now):
    with session_factory() as s:
        _news(s, now)
        s.commit()
        covered = _upcoming(s, now, timedelta(0), ABSENCES_KNOWN)
        later = _upcoming(s, now, ABSENCES_KNOWN + timedelta(hours=1), timedelta(days=5))
    statuses = set()
    for f in covered:
        body = client.get(f"/fixtures/{f.id}").json()
        for side in (body["team_news"]["home"], body["team_news"]["away"]):
            assert side["absences_status"] in {"reported", "none_reported"}
            assert (side["absences_status"] == "reported") == bool(side["absences"])
            statuses.add(side["absences_status"])
    assert statuses == {"reported", "none_reported"}
    for f in later[:3]:
        news = client.get(f"/fixtures/{f.id}").json()["team_news"]
        if news is not None:  # minutes known but nothing checked yet
            assert {news["home"]["absences_status"], news["away"]["absences_status"]} == {"unknown"}


def test_reads_as_of_ignore_what_was_stored_later(session_factory, seeded, now):
    from conftest import set_test_wall_clock

    with session_factory() as s:
        stored = now + timedelta(hours=2)
        set_test_wall_clock(s, stored)
        _news(s, now)  # captured "at now" but only stored two hours later
        f = _upcoming(s, now, timedelta(0), ABSENCES_KNOWN)[0]
        before = team_news(s, f, as_of=now + timedelta(hours=1))
        after = team_news(s, f, as_of=stored)
        assert after is not None
        assert {after.home.absences_status, after.away.absences_status} <= {
            "reported",
            "none_reported",
        }
        # an hour before storage: no absences, and no minutes counted either
        assert before is None or (
            before.home.absences_status == before.away.absences_status == "unknown"
            and before.home.recent_matches == before.away.recent_matches == 0
        )


def test_coverage_report_counts_only_what_the_decision_could_see(session_factory, seeded, now):
    from conftest import set_test_wall_clock

    with session_factory() as s:
        day = (now + timedelta(days=1)).date()  # decision at 09:00 KST = 00:00 UTC
        set_test_wall_clock(s, now)
        _news(s, now)
        report = coverage_on(s, NEWS, day)
        a = report["absences"]
        assert report["fixtures"] > 0 and report["team_slots"] == 2 * report["fixtures"]
        assert a["reported"] + a["none_reported"] + a["unknown"] == report["team_slots"]
        assert a["reported"] + a["none_reported"] > 0
        assert report["lineups_in"] <= report["team_slots"]

        # the same information stored after that decision would not count
        s.rollback()
    with session_factory() as s:
        decision = coverage_on(s, NEWS, day)["decision_at"]
        set_test_wall_clock(s, datetime.fromisoformat(decision) + timedelta(hours=1))
        _news(s, now)
        late = coverage_on(s, NEWS, day)
        assert late["absences"]["reported"] == late["absences"]["none_reported"] == 0


def test_rows_stored_after_the_moment_never_count_toward_regulars(db_session, seeded, now):
    """Codex QA MORN-1: a match collected partly before and partly after the
    decision only contributes the rows stored by then (the boundary included)."""
    from edge_api.db.models import PlayerAppearance
    from edge_api.services.team_news import regular_players

    fixture = db_session.scalars(select(Fixture).where(Fixture.kickoff_at < now).limit(1)).one()
    for pid, minutes, stored in (
        ("known", 10, now - timedelta(hours=1)),
        ("at-boundary", 20, now),
        ("future-star", 130, now + timedelta(seconds=1)),
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
                created_at=stored,
            )
        )
    db_session.flush()
    players, matches = regular_players(db_session, fixture.home_team_id, now, known_by=now)
    ids = {pid for pid, _ in players}
    assert matches >= 1 and {"known", "at-boundary"} <= ids and "future-star" not in ids
    everyone, _ = regular_players(db_session, fixture.home_team_id, now)
    assert "future-star" in {pid for pid, _ in everyone}
