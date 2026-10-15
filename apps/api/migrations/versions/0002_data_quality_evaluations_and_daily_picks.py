"""data quality, evaluations and daily picks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 16:26:14.157216
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Audit/history tables are append-only, like odds_snapshots and predictions
# (reject_mutation() is defined in 0001). Later facts are new rows.
APPEND_ONLY_TABLES = ("ingestion_runs", "model_evaluations", "daily_picks", "daily_pick_events")


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(
        "ix_ingestion_runs_provider_finished",
        "ingestion_runs",
        ["provider", "finished_at"],
        unique=False,
    )
    op.create_table(
        "model_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("feature_set", sa.String(length=128), nullable=False),
        sa.Column("dataset", sa.String(length=128), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_evaluations")),
        sa.UniqueConstraint("report_sha256", name=op.f("uq_model_evaluations_report_sha256")),
    )
    op.create_table(
        "daily_picks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("pick_date", sa.Date(), nullable=False),
        sa.Column("tz", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=True),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("model_version_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=8), nullable=True),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("input_data_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status <> 'published' OR (fixture_id IS NOT NULL AND prediction_id IS NOT NULL AND outcome IS NOT NULL AND probability BETWEEN 0 AND 1)",
            name=op.f("ck_daily_picks_published_pick_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["fixture_id"], ["fixtures.id"], name=op.f("fk_daily_picks_fixture_id_fixtures")
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_daily_picks_model_version_id_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["predictions.id"],
            name=op.f("fk_daily_picks_prediction_id_predictions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_picks")),
        sa.UniqueConstraint(
            "provider", "pick_date", "revision", name=op.f("uq_daily_picks_day_revision")
        ),
    )
    op.create_table(
        "daily_pick_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pick_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("actual_outcome", sa.String(length=8), nullable=True),
        sa.Column("hit", sa.Boolean(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pick_id"], ["daily_picks.id"], name=op.f("fk_daily_pick_events_pick_id_daily_picks")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_pick_events")),
        sa.UniqueConstraint("pick_id", "event", name=op.f("uq_daily_pick_events_one_per_kind")),
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_mutation()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_table("daily_pick_events")
    op.drop_table("daily_picks")
    op.drop_table("model_evaluations")
    op.drop_index("ix_ingestion_runs_provider_finished", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
