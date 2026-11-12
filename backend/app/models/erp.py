import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DatabaseConnection(Base):
    __tablename__ = "database_connections"
    __table_args__ = (
        CheckConstraint(
            "authentication_type IN ('sql_server', 'windows')",
            name="ck_database_connections_authentication_type",
        ),
        CheckConstraint(
            "erp_version IN ('nav_2013_r2', 'nav_2018', 'business_central', 'sql_server')",
            name="ck_database_connections_erp_version",
        ),
        CheckConstraint(
            "connection_status IN ('untested', 'connected', 'error')",
            name="ck_database_connections_status",
        ),
        Index("ix_database_connections_enabled", "enabled"),
        Index("ix_database_connections_company", "company_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    company_name: Mapped[str | None] = mapped_column(String(160))
    server: Mapped[str] = mapped_column(String(255), nullable=False)
    database_name: Mapped[str] = mapped_column(String(128), nullable=False)
    authentication_type: Mapped[str] = mapped_column(String(24), nullable=False)
    erp_version: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="untested", server_default="untested"
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_schema_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserDatabaseAccess(Base):
    __tablename__ = "user_database_access"
    __table_args__ = (
        CheckConstraint(
            "permission IN ('read', 'manage')", name="ck_user_database_access_permission"
        ),
        UniqueConstraint(
            "user_id", "database_connection_id", name="uq_user_database_access_user_db"
        ),
        Index("ix_user_database_access_database", "database_connection_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    database_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("database_connections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="read")
    granted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SchemaObject(Base):
    __tablename__ = "database_schema_objects"
    __table_args__ = (
        CheckConstraint("object_type IN ('table', 'view')", name="ck_schema_objects_type"),
        UniqueConstraint(
            "database_connection_id", "schema_name", "object_name", name="uq_schema_object_name"
        ),
        Index("ix_schema_objects_connection", "database_connection_id"),
        Index("ix_schema_objects_name", "object_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    database_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("database_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False, default="dbo")
    object_name: Mapped[str] = mapped_column(String(256), nullable=False)
    object_type: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    indexes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SchemaColumn(Base):
    __tablename__ = "database_schema_columns"
    __table_args__ = (
        UniqueConstraint("schema_object_id", "column_name", name="uq_schema_column_name"),
        Index("ix_schema_columns_object", "schema_object_id"),
        Index("ix_schema_columns_name", "column_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("database_schema_objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    column_name: Mapped[str] = mapped_column(String(256), nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    data_type: Mapped[str] = mapped_column(String(160), nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    default_value: Mapped[str | None] = mapped_column(Text)
    is_primary_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_foreign_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    caption: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)


class SchemaRelationship(Base):
    __tablename__ = "database_schema_relationships"
    __table_args__ = (
        Index("ix_schema_relationship_source", "source_object_id"),
        Index("ix_schema_relationship_target", "target_schema", "target_table"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("database_schema_objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_column: Mapped[str] = mapped_column(String(256), nullable=False)
    target_schema: Mapped[str] = mapped_column(String(128), nullable=False, default="dbo")
    target_table: Mapped[str] = mapped_column(String(256), nullable=False)
    target_column: Mapped[str] = mapped_column(String(256), nullable=False)
    constraint_name: Mapped[str | None] = mapped_column(String(256))


class CompanyMapping(Base):
    __tablename__ = "company_mappings"
    __table_args__ = (
        UniqueConstraint(
            "database_connection_id", "company_name", name="uq_company_mapping_connection_name"
        ),
        Index("ix_company_mappings_connection", "database_connection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    database_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("database_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_name: Mapped[str] = mapped_column(String(160), nullable=False)
    erp_version: Mapped[str] = mapped_column(String(32), nullable=False)
    table_mappings: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    field_mappings: Mapped[dict[str, dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    currency_code: Mapped[str | None] = mapped_column(String(3))
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BusinessDictionaryEntry(Base):
    __tablename__ = "business_dictionary"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('term', 'table', 'column', 'metric', 'rule')",
            name="ck_business_dictionary_entry_type",
        ),
        Index("ix_business_dictionary_connection", "database_connection_id"),
        Index("ix_business_dictionary_term", "term"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term: Mapped[str] = mapped_column(String(120), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False, default="term")
    database_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("database_connections.id", ondelete="CASCADE")
    )
    company_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company_mappings.id", ondelete="CASCADE")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
        Index("ix_conversations_database", "database_connection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    database_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("database_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company_mappings.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    active_filters: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_messages_role"),
        Index("ix_conversation_messages_order", "conversation_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str | None] = mapped_column(Text)
    result_columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    result_rows: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SavedDashboard(Base):
    __tablename__ = "saved_dashboards"
    __table_args__ = (
        Index("ix_saved_dashboards_user_updated", "user_id", "updated_at"),
        Index("ix_saved_dashboards_user_favorite", "user_id", "is_favorite", "updated_at"),
        Index("ix_saved_dashboards_database", "database_connection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    database_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("database_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company_mappings.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DashboardVersion(Base):
    __tablename__ = "dashboard_versions"
    __table_args__ = (
        UniqueConstraint("dashboard_id", "version_number", name="uq_dashboard_version_number"),
        CheckConstraint("version_number > 0", name="ck_dashboard_version_positive"),
        Index("ix_dashboard_versions_dashboard_created", "dashboard_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("saved_dashboards.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
