"""ORM models.

Conventions
- Every timestamp is ``timestamptz`` and written in UTC.
- ``odds_snapshots`` and ``predictions`` are APPEND-ONLY: a DB trigger rejects
  UPDATE/DELETE (see migration 0001). New information => new row.
- Natural/idempotency keys are enforced with UNIQUE constraints so ingestion and
  prediction jobs can be re-run safely with ``INSERT ... ON CONFLICT DO NOTHING``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(constraint_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = NAMING_CONVENTION  # type: ignore[assignment]


class FixtureStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


def _ts(**kw: Any) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), **kw)


class LeagueType(StrEnum):
    LEAGUE = "league"  # one table of teams playing each other -> the model applies
    CUP = "cup"  # knockout / mixed competitions -> no predictions (teams from many leagues)


class League(Base):
    """A competition as the provider defines it (mutable reference data, upserted)."""

    __tablename__ = "leagues"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="provider_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80))
    country_code: Mapped[str | None] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(16), default=LeagueType.LEAGUE.value)
    current_season: Mapped[str | None] = mapped_column(String(16))
    season_year: Mapped[int | None] = mapped_column(Integer)  # provider's season key
    has_odds: Mapped[bool] = mapped_column(Boolean, default=False)
    # the provider reports injuries/suspensions for this league (absences coverage)
    has_injuries: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    logo_url: Mapped[str | None] = mapped_column(String(255))
    flag_url: Mapped[str | None] = mapped_column(String(255))
    # Results are complete up to this instant (history backfill + rolling date
    # window). NULL or older than the rolling window -> the league needs a backfill
    # before it can be predicted.
    results_synced_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now())


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="provider_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    short_name: Mapped[str] = mapped_column(String(10))
    logo_url: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now())


class Fixture(Base):
    __tablename__ = "fixtures"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="provider_key"),
        CheckConstraint("home_team_id <> away_team_id", name="distinct_teams"),
        Index("ix_fixtures_kickoff_at", "kickoff_at"),
        Index("ix_fixtures_league_kickoff", "league_id", "kickoff_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    season: Mapped[str] = mapped_column(String(16))
    round: Mapped[int | None] = mapped_column(Integer)
    kickoff_at: Mapped[datetime] = _ts()
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[str] = mapped_column(String(16), default=FixtureStatus.SCHEDULED.value)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    # last time an overdue lookup asked the provider for this fixture (rotation)
    reconcile_checked_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now())

    league: Mapped[League] = relationship(lazy="joined")
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id], lazy="joined")
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id], lazy="joined")


class OddsSnapshot(Base):
    """One bookmaker's full 1X2 price set at one point in time (append-only)."""

    __tablename__ = "odds_snapshots"
    __table_args__ = (
        UniqueConstraint("fixture_id", "bookmaker", "market", "captured_at", name="snapshot_key"),
        CheckConstraint("odds_home > 1 AND odds_draw > 1 AND odds_away > 1", name="odds_gt_one"),
        Index("ix_odds_snapshots_fixture_captured", "fixture_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    provider: Mapped[str] = mapped_column(String(32))
    bookmaker: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(16), default="1X2")
    odds_home: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    odds_draw: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    odds_away: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    captured_at: Mapped[datetime] = _ts()
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts(server_default=func.now())

    fixture: Mapped[Fixture] = relationship()


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint(
            "name", "version", "git_sha", "feature_set", "code_fingerprint", name="identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))  # explicit semver
    git_sha: Mapped[str] = mapped_column(String(40))
    # SHA-256 of the model/API/ingestion source (edge_api.versioning); NULL on rows
    # written before it was recorded
    code_fingerprint: Mapped[str | None] = mapped_column(String(64))
    feature_set: Mapped[str] = mapped_column(String(128))
    calibration: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    artifact_uri: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class Prediction(Base):
    """Immutable pre-match prediction snapshot.

    Idempotency key: (fixture, model version, odds snapshot, input_data_as_of).
    Re-running the job with identical inputs inserts nothing; changed inputs
    append a new row while older rows stay untouched for auditing/backtests.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "fixture_id",
            "model_version_id",
            "market_odds_snapshot_id",
            "input_data_as_of",
            name="idempotency_key",
        ),
        CheckConstraint(
            "abs(probability_home + probability_draw + probability_away - 1) < 1e-6",
            name="probabilities_sum_to_one",
        ),
        CheckConstraint(
            "probability_home BETWEEN 0 AND 1 AND probability_draw BETWEEN 0 AND 1 "
            "AND probability_away BETWEEN 0 AND 1",
            name="probabilities_in_range",
        ),
        Index("ix_predictions_fixture_created", "fixture_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    market_odds_snapshot_id: Mapped[int] = mapped_column(ForeignKey("odds_snapshots.id"))
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    input_data_as_of: Mapped[datetime] = _ts()
    probability_home: Mapped[float] = mapped_column(Float)
    probability_draw: Mapped[float] = mapped_column(Float)
    probability_away: Mapped[float] = mapped_column(Float)
    expected_goals_home: Mapped[float] = mapped_column(Float)
    expected_goals_away: Mapped[float] = mapped_column(Float)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)

    fixture: Mapped[Fixture] = relationship()
    model_version: Mapped[ModelVersion] = relationship(lazy="joined")
    odds_snapshot: Mapped[OddsSnapshot] = relationship(lazy="joined")


class IngestionRun(Base):
    """One pipeline run (ingest + predict) per row: the data-freshness audit log."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_ingestion_runs_provider_finished", "provider", "finished_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime] = _ts()
    status: Mapped[str] = mapped_column(String(16))  # success | failed
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class ModelEvaluation(Base):
    """A stored backtest report (append-only, deduplicated by content hash)."""

    __tablename__ = "model_evaluations"
    __table_args__ = (UniqueConstraint("report_sha256", name="report_sha256"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    feature_set: Mapped[str] = mapped_column(String(128))
    dataset: Mapped[str] = mapped_column(String(128))
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    report_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class DailyPickStatus(StrEnum):
    PUBLISHED = "published"
    NO_QUALIFYING_MATCH = "no_qualifying_match"
    NO_MATCHES = "no_matches"


class DailyPick(Base):
    """The Today's Pick decision for one local day, frozen at publication.

    Append-only: later facts (result, cancellation) are DailyPickEvent rows.
    ``revision`` > 1 only exists when the replace-on-void policy is enabled.
    """

    __tablename__ = "daily_picks"
    __table_args__ = (
        UniqueConstraint("provider", "pick_date", "revision", name="day_revision"),
        CheckConstraint(
            "status <> 'published' OR (fixture_id IS NOT NULL AND prediction_id IS NOT NULL "
            "AND outcome IS NOT NULL AND probability BETWEEN 0 AND 1)",
            name="published_pick_complete",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    pick_date: Mapped[date] = mapped_column(Date)
    tz: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))
    fixture_id: Mapped[int | None] = mapped_column(ForeignKey("fixtures.id"))
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    outcome: Mapped[str | None] = mapped_column(String(8))
    probability: Mapped[float | None] = mapped_column(Float)
    input_data_as_of: Mapped[datetime | None] = _ts(nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published_at: Mapped[datetime] = _ts(server_default=func.now())

    fixture: Mapped[Fixture | None] = relationship(lazy="joined")
    prediction: Mapped[Prediction | None] = relationship(lazy="joined")
    events: Mapped[list[DailyPickEvent]] = relationship(
        lazy="selectin", order_by="DailyPickEvent.id"
    )


class DailyPickEvent(Base):
    """Facts learned after publication: 'settled' (result) or 'voided' (reason)."""

    __tablename__ = "daily_pick_events"
    __table_args__ = (UniqueConstraint("pick_id", "event", name="one_per_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pick_id: Mapped[int] = mapped_column(ForeignKey("daily_picks.id"))
    event: Mapped[str] = mapped_column(String(16))  # settled | voided
    actual_outcome: Mapped[str | None] = mapped_column(String(8))
    hit: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class TeamNewsKind(StrEnum):
    LINEUP = "lineup"  # official starting XI (published shortly before kickoff)
    ABSENCES = "absences"  # injured / suspended / doubtful players (days before)


class TeamNewsSnapshot(Base):
    """What was known about one team's line-up for one fixture at a point in time.

    Append-only: a report that differs from the team's latest one is a new row
    (also a return to an earlier report); re-fetching the latest report is a
    no-op, so polling before kickoff never duplicates rows. An absences snapshot
    with no players means the provider checked and reported none.
    """

    __tablename__ = "team_news_snapshots"
    __table_args__ = (
        Index("ix_team_news_fixture_kind_captured", "fixture_id", "kind", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    provider: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    captured_at: Mapped[datetime] = _ts()
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class PlayerAppearance(Base):
    """Minutes a player played in a finished fixture (append-only fact).

    Used to tell regular starters from squad players, so a published line-up can
    be described as "usual XI" or "n regulars missing".
    """

    __tablename__ = "player_appearances"
    __table_args__ = (
        UniqueConstraint("fixture_id", "player_provider_id", name="fixture_player"),
        Index("ix_player_appearances_team", "team_id", "fixture_id"),
        CheckConstraint("minutes >= 0 AND minutes <= 130", name="minutes_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    provider: Mapped[str] = mapped_column(String(32))
    player_provider_id: Mapped[str] = mapped_column(String(64))
    player_name: Mapped[str] = mapped_column(String(120))
    started: Mapped[bool] = mapped_column(Boolean)
    minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class ShadowForecast(Base):
    """One fixture's candidate forecasts at a day's pick decision time, recorded
    next to the production prediction and never shown (append-only).

    Every fixture of the pick window gets a row: ``recorded`` with all
    candidates, or ``excluded`` with the reason (no prediction, no market odds,
    stale odds, ...), so the comparison set and its exclusions stay auditable.
    The candidate definitions are fixed by ``protocol`` (edge_ml.shadow).
    """

    __tablename__ = "shadow_forecasts"
    __table_args__ = (
        UniqueConstraint("provider", "decision_date", "protocol", "fixture_id", name="one_per_day"),
        Index("ix_shadow_forecasts_decision", "provider", "protocol", "decision_date"),
        CheckConstraint("status IN ('recorded', 'excluded')", name="status_known"),
        CheckConstraint(
            "(status = 'recorded') = (forecasts IS NOT NULL AND excluded_reason IS NULL)",
            name="recorded_has_forecasts",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    protocol: Mapped[str] = mapped_column(String(32))
    decision_date: Mapped[date] = mapped_column(Date)
    decided_at: Mapped[datetime] = _ts()
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    kickoff_at: Mapped[datetime] = _ts()  # as known at the decision
    in_pick_scope: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16))
    excluded_reason: Mapped[str | None] = mapped_column(String(64))
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    prediction_created_at: Mapped[datetime | None] = _ts()
    input_data_as_of: Mapped[datetime | None] = _ts()
    odds_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("odds_snapshots.id"))
    bookmaker: Mapped[str | None] = mapped_column(String(64))
    odds_captured_at: Mapped[datetime | None] = _ts()
    odds_stored_at: Mapped[datetime | None] = _ts()
    forecasts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    build: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class FixtureObservation(Base):
    """What we knew about a fixture's state, and when (append-only).

    A row is written whenever ingestion stores a change to the status, kickoff
    or score, so the first time a result was available and any later correction
    stay on record (``fixtures`` itself only holds the latest state).
    ``created_at`` is when the state was stored: the earliest moment a decision
    could have seen it. Rows from migration 0008 (``source="backfill"``) use the
    fixture's ``updated_at`` then, an upper bound of the true first observation.
    """

    __tablename__ = "fixture_observations"
    __table_args__ = (Index("ix_fixture_observations_fixture", "fixture_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    kickoff_at: Mapped[datetime] = _ts()
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="ingest")
    created_at: Mapped[datetime] = _ts(server_default=func.now())


class MatchStatistic(Base):
    """One team's post-match statistics as the provider reported them (append-only).

    ``expected_goals`` is the provider's xG, None where it publishes none; it is
    a fact about a finished match, never an input about that match itself.
    ``created_at`` is when it was stored (the earliest moment a later decision
    could use it). A changed report from the provider is a new row; ``source``
    is "ingest" for the pipeline and "backfill" for history collected later.
    """

    __tablename__ = "match_statistics"
    __table_args__ = (
        Index("ix_match_statistics_fixture_team", "fixture_id", "team_id", "created_at"),
        CheckConstraint("expected_goals IS NULL OR expected_goals >= 0", name="xg_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    provider: Mapped[str] = mapped_column(String(32))
    shots: Mapped[int | None] = mapped_column(Integer)
    shots_on_target: Mapped[int | None] = mapped_column(Integer)
    expected_goals: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    source: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _ts(server_default=func.now())
