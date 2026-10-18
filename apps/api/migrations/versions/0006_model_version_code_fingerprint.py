"""model_versions.code_fingerprint: identify the exact code of a model version

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ["name", "version", "git_sha", "feature_set"]


def upgrade() -> None:
    # Rows written before this revision keep NULL: their code is not known.
    op.add_column("model_versions", sa.Column("code_fingerprint", sa.String(64), nullable=True))
    op.drop_constraint(op.f("uq_model_versions_identity"), "model_versions", type_="unique")
    op.create_unique_constraint(
        op.f("uq_model_versions_identity"), "model_versions", [*OLD, "code_fingerprint"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_model_versions_identity"), "model_versions", type_="unique")
    op.create_unique_constraint(op.f("uq_model_versions_identity"), "model_versions", OLD)
    op.drop_column("model_versions", "code_fingerprint")
