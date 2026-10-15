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


def last_successful_run(session: Session, provider: str) -> IngestionRun | None:
    return session.scalars(
        select(IngestionRun)
        .where(IngestionRun.provider == provider, IngestionRun.status == "success")
        .order_by(IngestionRun.finished_at.desc(), IngestionRun.id.desc())
        .limit(1)
    ).first()


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

    if last_run is None:
        add(QualityCheck("ingestion_recent", False, "no successful data collection recorded"))
    else:
        age = now - last_run.finished_at
        add(
            QualityCheck(
                "ingestion_recent",
                age <= timedelta(hours=settings.ingest_max_age_hours),
                f"last successful collection {age.total_seconds() / 3600:.1f}h ago",
            )
        )

    if prediction is None:
        add(QualityCheck("prediction_available", False, "no pre-match prediction"))
        return r
    add(QualityCheck("prediction_available", True, f"prediction #{prediction.id}"))

    mv = prediction.model_version
    current = mv.version == MODEL_VERSION and mv.feature_set == FEATURE_SET
    add(QualityCheck("current_model", current, f"model {mv.version} ({mv.feature_set})"))

    probs = (prediction.probability_home, prediction.probability_draw, prediction.probability_away)
    valid = all(math.isfinite(p) and 0 < p < 1 for p in probs) and abs(sum(probs) - 1) < 1e-6
    add(QualityCheck("probabilities_valid", valid, "sum to 1, each in (0, 1)"))

    odds_age = now - prediction.odds_snapshot.captured_at
    add(
        QualityCheck(
            "odds_fresh",
            odds_age <= timedelta(hours=settings.odds_max_age),
            f"odds captured {odds_age.total_seconds() / 3600:.1f}h ago "
            f"(max {settings.odds_max_age:.0f}h)",
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
