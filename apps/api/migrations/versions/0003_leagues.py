"""leagues: multi-league catalogue, fixtures.league_id, team/league logos

Existing fixtures (EPL only until now) are attached to a league row per
provider, so data collected before this migration keeps working.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 22:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (provider, old fixtures.league value) -> league row for data that already exists.
# The provider_id values match what the providers emit from now on, so the next
# ingestion run upserts these rows instead of creating duplicates.
KNOWN = {
    ("mock", "EPL"): ("eng-1", "Premier League", "England", "GB-ENG"),
    ("api_football", "EPL"): ("39", "Premier League", "England", "GB-ENG"),
}


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("country_code", sa.String(length=16), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("current_season", sa.String(length=16), nullable=True),
        sa.Column("season_year", sa.Integer(), nullable=True),
        sa.Column("has_odds", sa.Boolean(), nullable=False),
        sa.Column("logo_url", sa.String(length=255), nullable=True),
        sa.Column("flag_url", sa.String(length=255), nullable=True),
        sa.Column("results_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leagues")),
        sa.UniqueConstraint("provider", "provider_id", name=op.f("uq_leagues_provider_key")),
    )
    op.add_column("teams", sa.Column("logo_url", sa.String(length=255), nullable=True))
    op.add_column("fixtures", sa.Column("league_id", sa.Integer(), nullable=True))

    conn = op.get_bind()
    existing = conn.execute(sa.text("SELECT DISTINCT provider, league FROM fixtures")).all()
    for provider, league in existing:
        pid, name, country, code = KNOWN.get((provider, league), (league, league, "Unknown", None))
        league_id = conn.execute(
            sa.text(
                "INSERT INTO leagues (provider, provider_id, name, country, country_code, type,"
                " has_odds, results_synced_at)"
                " VALUES (:p, :pid, :name, :country, :code, 'league', true, now())"
                " RETURNING id"
            ),
            {"p": provider, "pid": pid, "name": name, "country": country, "code": code},
        ).scalar_one()
        conn.execute(
            sa.text(
                "UPDATE fixtures SET league_id = :lid WHERE provider = :p AND league = :league"
            ),
            {"lid": league_id, "p": provider, "league": league},
        )

    op.alter_column("fixtures", "league_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_fixtures_league_id_leagues"), "fixtures", "leagues", ["league_id"], ["id"]
    )
    op.create_index("ix_fixtures_league_kickoff", "fixtures", ["league_id", "kickoff_at"])
    op.drop_column("fixtures", "league")
    # teams play in several competitions, so a single league per team is meaningless
    op.drop_column("teams", "league")


def downgrade() -> None:
    op.add_column(
        "teams", sa.Column("league", sa.String(length=32), server_default="EPL", nullable=False)
    )
    op.add_column(
        "fixtures", sa.Column("league", sa.String(length=32), server_default="EPL", nullable=False)
    )
    op.drop_index("ix_fixtures_league_kickoff", table_name="fixtures")
    op.drop_constraint(op.f("fk_fixtures_league_id_leagues"), "fixtures", type_="foreignkey")
    op.drop_column("fixtures", "league_id")
    op.drop_column("teams", "logo_url")
    op.drop_table("leagues")
