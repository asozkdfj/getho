"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-15 10:25:17.268632
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APPEND_ONLY_TABLES = ("odds_snapshots", "predictions")

APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=False),
        sa.Column("feature_set", sa.String(length=128), nullable=False),
        sa.Column("calibration", sa.String(length=64), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("artifact_uri", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint(
            "name", "version", "git_sha", "feature_set", name=op.f("uq_model_versions_identity")
        ),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("short_name", sa.String(length=10), nullable=False),
        sa.Column("league", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("provider", "provider_id", name=op.f("uq_teams_provider_key")),
    )
    op.create_table(
        "fixtures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("league", sa.String(length=32), nullable=False),
        sa.Column("season", sa.String(length=16), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("home_team_id <> away_team_id", name=op.f("ck_fixtures_distinct_teams")),
        sa.ForeignKeyConstraint(
            ["away_team_id"], ["teams.id"], name=op.f("fk_fixtures_away_team_id_teams")
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"], ["teams.id"], name=op.f("fk_fixtures_home_team_id_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fixtures")),
        sa.UniqueConstraint("provider", "provider_id", name=op.f("uq_fixtures_provider_key")),
    )
    op.create_index("ix_fixtures_kickoff_at", "fixtures", ["kickoff_at"], unique=False)
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("bookmaker", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("odds_home", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("odds_draw", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("odds_away", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "odds_home > 1 AND odds_draw > 1 AND odds_away > 1",
            name=op.f("ck_odds_snapshots_odds_gt_one"),
        ),
        sa.ForeignKeyConstraint(
            ["fixture_id"], ["fixtures.id"], name=op.f("fk_odds_snapshots_fixture_id_fixtures")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_odds_snapshots")),
        sa.UniqueConstraint(
            "fixture_id",
            "bookmaker",
            "market",
            "captured_at",
            name=op.f("uq_odds_snapshots_snapshot_key"),
        ),
    )
    op.create_index(
        "ix_odds_snapshots_fixture_captured",
        "odds_snapshots",
        ["fixture_id", "captured_at"],
        unique=False,
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("model_version_id", sa.Integer(), nullable=False),
        sa.Column("market_odds_snapshot_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("input_data_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability_home", sa.Float(), nullable=False),
        sa.Column("probability_draw", sa.Float(), nullable=False),
        sa.Column("probability_away", sa.Float(), nullable=False),
        sa.Column("expected_goals_home", sa.Float(), nullable=False),
        sa.Column("expected_goals_away", sa.Float(), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "abs(probability_home + probability_draw + probability_away - 1) < 1e-6",
            name=op.f("ck_predictions_probabilities_sum_to_one"),
        ),
        sa.CheckConstraint(
            "probability_home BETWEEN 0 AND 1 AND probability_draw BETWEEN 0 AND 1 AND probability_away BETWEEN 0 AND 1",
            name=op.f("ck_predictions_probabilities_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["fixture_id"], ["fixtures.id"], name=op.f("fk_predictions_fixture_id_fixtures")
        ),
        sa.ForeignKeyConstraint(
            ["market_odds_snapshot_id"],
            ["odds_snapshots.id"],
            name=op.f("fk_predictions_market_odds_snapshot_id_odds_snapshots"),
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_predictions_model_version_id_model_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
        sa.UniqueConstraint(
            "fixture_id",
            "model_version_id",
            "market_odds_snapshot_id",
            "input_data_as_of",
            name=op.f("uq_predictions_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_predictions_fixture_created", "predictions", ["fixture_id", "created_at"], unique=False
    )

    # Snapshots are immutable history: forbid UPDATE/DELETE at the database level.
    # (TRUNCATE is still possible for operators/tests; it does not fire row triggers.)
    op.execute(APPEND_ONLY_FUNCTION)
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_mutation()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_mutation()")
    op.drop_index("ix_predictions_fixture_created", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("ix_odds_snapshots_fixture_captured", table_name="odds_snapshots")
    op.drop_table("odds_snapshots")
    op.drop_index("ix_fixtures_kickoff_at", table_name="fixtures")
    op.drop_table("fixtures")
    op.drop_table("teams")
    op.drop_table("model_versions")
