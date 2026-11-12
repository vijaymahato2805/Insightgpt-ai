"""Add persistent conversation memory and company currency metadata.

Revision ID: 0003_phase5_conversations_and_comparisons
Revises: 0002_sql_server_schema_and_dictionary
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_phase5_conversations_and_comparisons"
down_revision = "0002_sql_server_schema_and_dictionary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company_mappings", sa.Column("currency_code", sa.String(length=3), nullable=True))

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("database_connection_id", sa.Uuid(), nullable=False),
        sa.Column("company_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("active_filters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_mapping_id"], ["company_mappings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["database_connection_id"], ["database_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_user_updated", "conversations", ["user_id", "updated_at"]
    )
    op.create_index("ix_conversations_database", "conversations", ["database_connection_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("result_columns", sa.JSON(), nullable=False),
        sa.Column("result_rows", sa.JSON(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_messages_role"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_messages_order",
        "conversation_messages",
        ["conversation_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_order", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_database", table_name="conversations")
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_table("conversations")
    op.drop_column("company_mappings", "currency_code")
