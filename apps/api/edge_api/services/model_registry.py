from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.db.models import ModelVersion
from edge_api.versioning import resolve_git_sha
from edge_ml.model import FEATURE_SET, MODEL_NAME, MODEL_VERSION, PoissonEloModel


def get_or_create_model_version(session: Session, model: PoissonEloModel) -> ModelVersion:
    """Idempotently register (name, semver, git sha, feature set)."""
    identity = {
        "name": MODEL_NAME,
        "version": MODEL_VERSION,
        "git_sha": resolve_git_sha(),
        "feature_set": FEATURE_SET,
    }
    stmt = (
        insert(ModelVersion)
        .values(**identity, calibration=model.calibrator.name, params=model.params.to_dict())
        .on_conflict_do_nothing(constraint="uq_model_versions_identity")
    )
    session.execute(stmt)
    return session.scalars(select(ModelVersion).filter_by(**identity)).one()
