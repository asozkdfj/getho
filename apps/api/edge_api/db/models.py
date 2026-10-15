"""ORM models.

Conventions
- Every timestamp is ``timestamptz`` and written in UTC.
- ``odds_snapshots`` and ``predictions`` are APPEND-ONLY: a DB trigger rejects
  UPDATE/DELETE (see migration 0001). New information => new row.
- Natural/idempotency keys are enforced with UNIQUE constraints so ingestion and
  prediction jobs can be re-run safely with ``INSERT ... ON CONFLICT DO NOTHING``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
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


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="provider_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    short_name: Mapped[str] = mapped_column(String(10))
    league: Mapped[str] = mapped_column(String(32), default="EPL")
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now())


class Fixture(Base):
    __tablename__ = "fixtures"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="provider_key"),
        CheckConstraint("home_team_id <> away_team_id", name="distinct_teams"),
        Index("ix_fixtures_kickoff_at", "kickoff_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    league: Mapped[str] = mapped_column(String(32), default="EPL")
    season: Mapped[str] = mapped_column(String(16))
    round: Mapped[int | None] = mapped_column(Integer)
    kickoff_at: Mapped[datetime] = _ts()
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[str] = mapped_column(String(16), default=FixtureStatus.SCHEDULED.value)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts(server_default=func.now())
    updated_at: Mapped[datetime] = _ts(server_default=func.now())

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
        UniqueConstraint("name", "version", "git_sha", "feature_set", name="identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))  # explicit semver
    git_sha: Mapped[str] = mapped_column(String(40))
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
