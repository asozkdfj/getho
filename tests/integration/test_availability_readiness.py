"""Player data readiness report (counts only, never results)."""

from datetime import timedelta

from sqlalchemy import select, update

from edge_api.config import Settings
from edge_api.db.models import Fixture, TeamNewsSnapshot
from edge_ingestion.availability_readiness import readiness, summary
from edge_ingestion.providers import MockProvider
from edge_ingestion.team_news import ingest_post_match


def _with_minutes(s, now):
    ingest_post_match(
        s, MockProvider(now), now=now, scope=None, limit=5000, lookback=timedelta(days=400)
    )
    s.flush()


def _strip_time(report):
    return {k: v for k, v in report.items() if k != "generated_at"}


def test_counts_nest_and_split_live_from_backfill(session_factory, seeded, now):
    with session_factory() as s:
        _with_minutes(s, now)
        report = readiness(s, "mock")
    leagues = report["line_up_time"]["leagues"]
    assert leagues and report["outcome_blind"] is True
    for lg in leagues:
        for row in lg["seasons"].values():
            assert row["finished"] >= row["with_sheets"] >= row["full_xi"] >= row["strength_ready"]
            assert row["full_xi"] == row["full_xi_live"] + row["full_xi_backfill"]
    totals = [lg["totals"] for lg in leagues]
    assert sum(t["strength_ready"] for t in totals) > 0
    # stored at the test clock: only matches of the last two days count as live
    assert sum(t["full_xi_backfill"] for t in totals) > sum(t["full_xi_live"] for t in totals)
    # synthetic leagues are never verified
    assert report["line_up_time"]["strength_ready_verified_leagues"] == 0
    assert summary(report)["strength_ready_all_leagues"] == sum(t["strength_ready"] for t in totals)


def test_report_does_not_read_results(session_factory, seeded, now):
    with session_factory() as s:
        _with_minutes(s, now)
        before = readiness(s, "mock")
        s.execute(
            update(Fixture)
            .where(Fixture.status == "finished")
            .values(home_score=Fixture.away_score, away_score=Fixture.home_score)
        )
        after = readiness(s, "mock")
    assert _strip_time(before) == _strip_time(after)


def test_morning_counts_only_snapshots_stored_before_kickoff(session_factory, seeded, now):
    from conftest import set_test_wall_clock

    with session_factory() as s:
        done = s.scalars(
            select(Fixture).where(Fixture.status == "finished").order_by(Fixture.kickoff_at.desc())
        ).all()
        early, late = done[0], done[1]
        for f, stored in (
            (early, early.kickoff_at - timedelta(hours=30)),
            (late, late.kickoff_at + timedelta(hours=1)),
        ):
            set_test_wall_clock(s, stored)
            for team in (f.home_team_id, f.away_team_id):
                s.add(
                    TeamNewsSnapshot(
                        fixture_id=f.id,
                        team_id=team,
                        provider="mock",
                        kind="absences",
                        payload={"players": []},
                        content_hash=f"{f.id}-{team}",
                        captured_at=f.kickoff_at - timedelta(hours=30),
                    )
                )
            s.flush()
        absences = readiness(s, "mock")["morning_live"]["absences_both_teams"]
    # the late one was captured "before kickoff" but only stored after it
    assert absences == {"fixtures": 1, "median_hours_before": 30.0, "min_hours_before": 30.0}


def _absences(s, f, captured, stored):
    from conftest import set_test_wall_clock

    set_test_wall_clock(s, stored)
    for team in (f.home_team_id, f.away_team_id):
        s.add(
            TeamNewsSnapshot(
                fixture_id=f.id,
                team_id=team,
                provider="mock",
                kind="absences",
                payload={"players": []},
                content_hash=f"{f.id}-{team}-{stored.isoformat()}",
                captured_at=captured,
            )
        )
    s.flush()


def test_a_report_counts_from_when_it_was_stored(session_factory, seeded, now):
    """Codex QA AVAIL-TIME-1: captured 30 h before kickoff, stored 1 h before."""
    from edge_api.db.models import TeamNewsKind
    from edge_ingestion.availability_readiness import _first_captured, _lead_hours

    with session_factory() as s:
        f = s.scalars(
            select(Fixture).where(Fixture.status == "finished").order_by(Fixture.kickoff_at.desc())
        ).first()
        _absences(s, f, f.kickoff_at - timedelta(hours=30), f.kickoff_at - timedelta(hours=1))
        assert _lead_hours([f], _first_captured(s, TeamNewsKind.ABSENCES)) == [1.0]


def test_coverage_at_the_morning_decision(session_factory, seeded, now):
    """Known by the 09:00 KST decision of the pick day, or only later."""
    from edge_api.services.picks import local_day

    settings = Settings(data_provider="mock")
    with session_factory() as s:
        done = [
            f
            for f in s.scalars(
                select(Fixture)
                .where(Fixture.status == "finished")
                .order_by(Fixture.kickoff_at.desc())
            ).all()
            if f.kickoff_at - local_day(f.kickoff_at, settings).publish_at > timedelta(hours=3)
        ]
        on_time, late = done[0], done[1]
        decision = local_day(on_time.kickoff_at, settings).publish_at
        _absences(s, on_time, decision - timedelta(hours=5), decision - timedelta(hours=4))
        late_decision = local_day(late.kickoff_at, settings).publish_at
        _absences(s, late, late_decision - timedelta(hours=1), late_decision + timedelta(hours=1))
        cov = readiness(s, "mock", settings)["morning_live"]["absences_at_decision"]
    assert cov["both_teams"] == 1
    assert cov["fixtures"] >= 2  # every finished fixture decided since the first report
    assert cov["median_age_hours"] == 4.0
    # leagues without any absence report are counted apart, not listed as zeros
    in_scope = {on_time.league.name, late.league.name}
    assert all(row["league"].split(" - ", 1)[1] in in_scope for row in cov["leagues"])
    assert cov["out_of_scope_fixtures"] > 0  # the seed has more leagues than the two above
