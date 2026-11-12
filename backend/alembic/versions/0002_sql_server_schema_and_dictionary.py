"""Add SQL Server connections, discovered schema, mappings and dictionary.

Revision ID: 0002_sql_server_schema_and_dictionary
Revises: 0001_create_users
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_sql_server_schema_and_dictionary"
down_revision = "0001_create_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "database_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_name", sa.String(length=120), nullable=False),
        sa.Column("company_name", sa.String(length=160), nullable=True),
        sa.Column("server", sa.String(length=255), nullable=False),
        sa.Column("database_name", sa.String(length=128), nullable=False),
        sa.Column("authentication_type", sa.String(length=24), nullable=False),
        sa.Column("erp_version", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("connection_status", sa.String(length=16), server_default="untested", nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_schema_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "authentication_type IN ('sql_server', 'windows')",
            name="ck_database_connections_authentication_type",
        ),
        sa.CheckConstraint(
            "erp_version IN ('nav_2013_r2', 'nav_2018', 'business_central', 'sql_server')",
            name="ck_database_connections_erp_version",
        ),
        sa.CheckConstraint(
            "connection_status IN ('untested', 'connected', 'error')",
            name="ck_database_connections_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_name", name="uq_database_connections_connection_name"),
    )
    op.create_index("ix_database_connections_enabled", "database_connections", ["enabled"])
    op.create_index("ix_database_connections_company", "database_connections", ["company_name"])

    op.create_table(
        "user_database_access",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("database_connection_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("permission IN ('read', 'manage')", name="ck_user_database_access_permission"),
        sa.ForeignKeyConstraint(["database_connection_id"], ["database_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "database_connection_id"),
        sa.UniqueConstraint("user_id", "database_connection_id", name="uq_user_database_access_user_db"),
    )
    op.create_index("ix_user_database_access_database", "user_database_access", ["database_connection_id"])

    op.create_table(
        "database_schema_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("database_connection_id", sa.Uuid(), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=False),
        sa.Column("object_name", sa.String(length=256), nullable=False),
        sa.Column("object_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("indexes", sa.JSON(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("object_type IN ('table', 'view')", name="ck_schema_objects_type"),
        sa.ForeignKeyConstraint(["database_connection_id"], ["database_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "database_connection_id", "schema_name", "object_name", name="uq_schema_object_name"
        ),
    )
    op.create_index("ix_schema_objects_connection", "database_schema_objects", ["database_connection_id"])
    op.create_index("ix_schema_objects_name", "database_schema_objects", ["object_name"])

    op.create_table(
        "database_schema_columns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_object_id", sa.Uuid(), nullable=False),
        sa.Column("column_name", sa.String(length=256), nullable=False),
        sa.Column("ordinal_position", sa.Integer(), nullable=False),
        sa.Column("data_type", sa.String(length=160), nullable=False),
        sa.Column("nullable", sa.Boolean(), nullable=False),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("is_primary_key", sa.Boolean(), nullable=False),
        sa.Column("is_foreign_key", sa.Boolean(), nullable=False),
        sa.Column("caption", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["schema_object_id"], ["database_schema_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schema_object_id", "column_name", name="uq_schema_column_name"),
    )
    op.create_index("ix_schema_columns_object", "database_schema_columns", ["schema_object_id"])
    op.create_index("ix_schema_columns_name", "database_schema_columns", ["column_name"])

    op.create_table(
        "database_schema_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_object_id", sa.Uuid(), nullable=False),
        sa.Column("source_column", sa.String(length=256), nullable=False),
        sa.Column("target_schema", sa.String(length=128), nullable=False),
        sa.Column("target_table", sa.String(length=256), nullable=False),
        sa.Column("target_column", sa.String(length=256), nullable=False),
        sa.Column("constraint_name", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["source_object_id"], ["database_schema_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schema_relationship_source", "database_schema_relationships", ["source_object_id"])
    op.create_index(
        "ix_schema_relationship_target",
        "database_schema_relationships",
        ["target_schema", "target_table"],
    )

    op.create_table(
        "company_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("database_connection_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=160), nullable=False),
        sa.Column("erp_version", sa.String(length=32), nullable=False),
        sa.Column("table_mappings", sa.JSON(), nullable=False),
        sa.Column("field_mappings", sa.JSON(), nullable=False),
        sa.Column("is_auto_generated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["database_connection_id"], ["database_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "database_connection_id", "company_name", name="uq_company_mapping_connection_name"
        ),
    )
    op.create_index("ix_company_mappings_connection", "company_mappings", ["database_connection_id"])

    op.create_table(
        "business_dictionary",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("term", sa.String(length=120), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=False),
        sa.Column("database_connection_id", sa.Uuid(), nullable=True),
        sa.Column("company_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "entry_type IN ('term', 'table', 'column', 'metric', 'rule')",
            name="ck_business_dictionary_entry_type",
        ),
        sa.ForeignKeyConstraint(["company_mapping_id"], ["company_mappings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["database_connection_id"], ["database_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_dictionary_connection", "business_dictionary", ["database_connection_id"])
    op.create_index("ix_business_dictionary_term", "business_dictionary", ["term"])


def downgrade() -> None:
    op.drop_index("ix_business_dictionary_term", table_name="business_dictionary")
    op.drop_index("ix_business_dictionary_connection", table_name="business_dictionary")
    op.drop_table("business_dictionary")
    op.drop_index("ix_company_mappings_connection", table_name="company_mappings")
    op.drop_table("company_mappings")
    op.drop_index("ix_schema_relationship_target", table_name="database_schema_relationships")
    op.drop_index("ix_schema_relationship_source", table_name="database_schema_relationships")
    op.drop_table("database_schema_relationships")
    op.drop_index("ix_schema_columns_name", table_name="database_schema_columns")
    op.drop_index("ix_schema_columns_object", table_name="database_schema_columns")
    op.drop_table("database_schema_columns")
    op.drop_index("ix_schema_objects_name", table_name="database_schema_objects")
    op.drop_index("ix_schema_objects_connection", table_name="database_schema_objects")
    op.drop_table("database_schema_objects")
    op.drop_index("ix_user_database_access_database", table_name="user_database_access")
    op.drop_table("user_database_access")
    op.drop_index("ix_database_connections_company", table_name="database_connections")
    op.drop_index("ix_database_connections_enabled", table_name="database_connections")
    op.drop_table("database_connections")
