"""Add saved dashboard configurations, favorites, and version history.

Revision ID: 0004_phase6_saved_dashboards
Revises: 0003_phase5_conversations_and_comparisons
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_phase6_saved_dashboards"
down_revision = "0003_phase5_conversations_and_comparisons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_dashboards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("database_connection_id", sa.Uuid(), nullable=False),
        sa.Column("company_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["database_connection_id"], ["database_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["company_mapping_id"], ["company_mappings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_saved_dashboards_user_updated", "saved_dashboards", ["user_id", "updated_at"]
    )
    op.create_index(
        "ix_saved_dashboards_user_favorite",
        "saved_dashboards",
        ["user_id", "is_favorite", "updated_at"],
    )
    op.create_index(
        "ix_saved_dashboards_database", "saved_dashboards", ["database_connection_id"]
    )

    op.create_table(
        "dashboard_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version_number > 0", name="ck_dashboard_version_positive"),
        sa.ForeignKeyConstraint(["dashboard_id"], ["saved_dashboards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dashboard_id", "version_number", name="uq_dashboard_version_number"),
    )
    op.create_index(
        "ix_dashboard_versions_dashboard_created",
        "dashboard_versions",
        ["dashboard_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_versions_dashboard_created", table_name="dashboard_versions")
    op.drop_table("dashboard_versions")
    op.drop_index("ix_saved_dashboards_database", table_name="saved_dashboards")
    op.drop_index("ix_saved_dashboards_user_favorite", table_name="saved_dashboards")
    op.drop_index("ix_saved_dashboards_user_updated", table_name="saved_dashboards")
    op.drop_table("saved_dashboards")
