"""fixtures.reconcile_checked_at: rotate overdue fixture lookups

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fixtures",
        sa.Column("reconcile_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fixtures", "reconcile_checked_at")
