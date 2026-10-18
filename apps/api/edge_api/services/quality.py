"""Data-quality gate for one match prediction.

Every check is explicit and reported, so a UI can show *why* a match is not
eligible (e.g. for Today's Pick) instead of silently producing a number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import Fixture, FixtureStatus, IngestionRun, Prediction
from edge_ml.model import FEATURE_SET, MODEL_VERSION


@dataclass(frozen=True, slots=True)
class QualityCheck:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class QualityReport:
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed(self) -> list[QualityCheck]:
        return [c for c in self.checks if not c.passed]


def last_successful_run(
    session: Session, provider: str, as_of: datetime | None = None
) -> IngestionRun | None:
    """The latest successful run, or the latest one finished by ``as_of``."""
    query = select(IngestionRun).where(
        IngestionRun.provider == provider, IngestionRun.status == "success"
    )
    if as_of is not None:
        query = query.where(IngestionRun.finished_at <= as_of)
    return session.scalars(
        query.order_by(IngestionRun.finished_at.desc(), IngestionRun.id.desc()).limit(1)
    ).first()


def _within(age: timedelta, max_age: timedelta) -> bool:
    """Not older than ``max_age`` and not from after the decision time."""
    return timedelta(0) <= age <= max_age


def _age_detail(what: str, age: timedelta) -> str:
    hours = age.total_seconds() / 3600
    if hours < 0:
        return f"{what} {-hours:.1f}h after the decision time"
    return f"{what} {hours:.1f}h ago"


def assess(
    fixture: Fixture,
    prediction: Prediction | None,
    *,
    now: datetime,
    settings: Settings,
    last_run: IngestionRun | None,
) -> QualityReport:
    r = QualityReport()
    add = r.checks.append

    upcoming = fixture.status == FixtureStatus.SCHEDULED.value and fixture.kickoff_at > now
    add(QualityCheck("upcoming", upcoming, f"status={fixture.status}"))

    if last_run is None or last_run.finished_at is None:
        add(QualityCheck("ingestion_recent", False, "no successful data collection recorded"))
    else:
        age = now - last_run.finished_at
        add(
            QualityCheck(
                "ingestion_recent",
                _within(age, timedelta(hours=settings.ingest_max_age_hours)),
                _age_detail("last successful collection", age),
            )
        )

    if prediction is None:
        add(QualityCheck("prediction_available", False, "no pre-match prediction"))
        return r
    add(QualityCheck("prediction_available", True, f"prediction #{prediction.id}"))

    # Point in time: the prediction and its inputs must exist at the decision
    # time. A missing timestamp fails closed.
    created, as_of = prediction.created_at, prediction.input_data_as_of
    timely = created is not None and as_of is not None and created <= now and as_of <= now
    add(
        QualityCheck(
            "prediction_timely",
            timely,
            "created and inputs as of before the decision time"
            if timely
            else f"created {created}, inputs as of {as_of}, decision {now}",
        )
    )

    mv = prediction.model_version
    current = mv.version == MODEL_VERSION and mv.feature_set == FEATURE_SET
    add(QualityCheck("current_model", current, f"model {mv.version} ({mv.feature_set})"))

    probs = (prediction.probability_home, prediction.probability_draw, prediction.probability_away)
    valid = all(math.isfinite(p) and 0 < p < 1 for p in probs) and abs(sum(probs) - 1) < 1e-6
    add(QualityCheck("probabilities_valid", valid, "sum to 1, each in (0, 1)"))

    snapshot = prediction.odds_snapshot
    if snapshot is None or snapshot.captured_at is None:
        add(QualityCheck("odds_fresh", False, "no odds snapshot"))
    else:
        odds_age = now - snapshot.captured_at
        add(
            QualityCheck(
                "odds_fresh",
                _within(odds_age, timedelta(hours=settings.odds_max_age)),
                _age_detail("odds captured", odds_age) + f" (max {settings.odds_max_age:.0f}h)",
            )
        )

    features = prediction.features or {}
    n_home, n_away = features.get("matches_home"), features.get("matches_away")
    enough = (
        isinstance(n_home, int)
        and isinstance(n_away, int)
        and min(n_home, n_away) >= settings.min_team_matches
    )
    add(
        QualityCheck(
            "team_history",
            enough,
            f"matches in model history: home={n_home}, away={n_away} "
            f"(min {settings.min_team_matches})",
        )
    )
    return r
