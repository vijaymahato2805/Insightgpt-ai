import re
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class AuthenticationType(str, Enum):
    SQL_SERVER = "sql_server"
    WINDOWS = "windows"


class ERPVersion(str, Enum):
    NAV_2013_R2 = "nav_2013_r2"
    NAV_2018 = "nav_2018"
    BUSINESS_CENTRAL = "business_central"
    SQL_SERVER = "sql_server"


class DatabaseConnectionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_name: str = Field(min_length=2, max_length=120)
    company_name: str | None = Field(default=None, max_length=160)
    server: str = Field(min_length=1, max_length=255)
    database: str = Field(min_length=1, max_length=128)
    authentication_type: AuthenticationType
    username: str | None = Field(default=None, max_length=256)
    password: SecretStr | None = None
    erp_version: ERPVersion
    enabled: bool = True

    @field_validator("connection_name", "server", "database")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("company_name", "username")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_auth_fields(self) -> "DatabaseConnectionWrite":
        if not self.connection_name or not self.server or not self.database:
            raise ValueError("Connection name, server, and database are required")
        if self.company_name == "":
            raise ValueError("company_name must not be blank")
        if self.authentication_type is AuthenticationType.SQL_SERVER and not self.username:
            raise ValueError("username is required for SQL Server authentication")
        if self.authentication_type is AuthenticationType.WINDOWS and (
            self.username or self.password
        ):
            raise ValueError("Windows Authentication does not accept username or password fields")
        return self


class DatabaseConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_name: str | None = Field(default=None, min_length=2, max_length=120)
    company_name: str | None = Field(default=None, max_length=160)
    server: str | None = Field(default=None, min_length=1, max_length=255)
    database: str | None = Field(default=None, min_length=1, max_length=128)
    authentication_type: AuthenticationType | None = None
    username: str | None = Field(default=None, max_length=256)
    password: SecretStr | None = None
    erp_version: ERPVersion | None = None
    enabled: bool | None = None

    @field_validator("connection_name", "server", "database")
    @classmethod
    def trim_required_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("company_name", "username")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "DatabaseConnectionUpdate":
        required = {
            "connection_name",
            "server",
            "database",
            "authentication_type",
            "erp_version",
            "enabled",
        }
        for name in required & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        for name in {"connection_name", "server", "database"} & self.model_fields_set:
            if not getattr(self, name):
                raise ValueError(f"{name} must not be blank")
        return self


class DatabaseConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connection_name: str
    company_name: str | None
    server: str
    database: str = Field(validation_alias="database_name")
    authentication_type: AuthenticationType
    erp_version: ERPVersion
    enabled: bool
    connection_status: str
    last_tested_at: datetime | None
    last_schema_refresh_at: datetime | None
    has_credentials: bool = Field(validation_alias="credentials_encrypted")
    created_at: datetime

    @field_validator("has_credentials", mode="before")
    @classmethod
    def hide_secret_value(cls, value: str | None) -> bool:
        return bool(value)


class DatabaseConnectionList(BaseModel):
    items: list[DatabaseConnectionResponse]


class DatabaseTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID | None = None
    connection: DatabaseConnectionWrite | None = None

    @model_validator(mode="after")
    def require_one_target(self) -> "DatabaseTestRequest":
        if (self.database_id is None) == (self.connection is None):
            raise ValueError("Provide exactly one of database_id or connection")
        return self


class DatabaseTestResponse(BaseModel):
    success: bool
    message: str


class AccessPermission(str, Enum):
    READ = "read"
    MANAGE = "manage"


class DatabaseAccessWrite(BaseModel):
    permission: AccessPermission = AccessPermission.READ


class DatabaseAccessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    database_connection_id: UUID
    permission: AccessPermission


class DatabaseAccessList(BaseModel):
    items: list[DatabaseAccessResponse]


class CompanyMappingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_connection_id: UUID
    company_name: str = Field(min_length=1, max_length=160)
    table_mappings: dict[str, str] = Field(default_factory=dict)
    field_mappings: dict[str, dict[str, str]] = Field(default_factory=dict)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("company_name")
    @classmethod
    def trim_company_name(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("company_name must not be blank")
        return result

    @field_validator("currency_code")
    @classmethod
    def normalize_currency_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("currency_code must be a three-letter currency code")
        return normalized

    @field_validator("table_mappings")
    @classmethod
    def validate_table_mappings(cls, values: dict[str, str]) -> dict[str, str]:
        for canonical, actual in values.items():
            _validate_mapping_name(canonical, "canonical table key")
            _validate_mapping_name(actual, "mapped table name")
        return values

    @field_validator("field_mappings")
    @classmethod
    def validate_field_mappings(
        cls, values: dict[str, dict[str, str]]
    ) -> dict[str, dict[str, str]]:
        for entity, fields in values.items():
            _validate_mapping_name(entity, "canonical entity key")
            for canonical, actual in fields.items():
                _validate_mapping_name(canonical, "canonical field key")
                _validate_mapping_name(actual, "mapped field name")
        return values


class CompanyMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    database_connection_id: UUID
    company_name: str
    erp_version: ERPVersion
    table_mappings: dict[str, str]
    field_mappings: dict[str, dict[str, str]]
    currency_code: str | None
    is_auto_generated: bool
    created_at: datetime
    updated_at: datetime


class CompanyMappingList(BaseModel):
    items: list[CompanyMappingResponse]


class DictionaryEntryType(str, Enum):
    TERM = "term"
    TABLE = "table"
    COLUMN = "column"
    METRIC = "metric"
    RULE = "rule"


class BusinessDictionaryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=5000)
    entry_type: DictionaryEntryType = DictionaryEntryType.TERM
    database_connection_id: UUID | None = None
    company_mapping_id: UUID | None = None
    enabled: bool = True

    @field_validator("term", "definition")
    @classmethod
    def trim_text(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("term and definition must not be blank")
        return result


class BusinessDictionaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    term: str
    definition: str
    entry_type: DictionaryEntryType
    database_connection_id: UUID | None
    company_mapping_id: UUID | None
    enabled: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class BusinessDictionaryList(BaseModel):
    items: list[BusinessDictionaryResponse]


class SchemaColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    column_name: str
    ordinal_position: int
    data_type: str
    nullable: bool
    default_value: str | None
    is_primary_key: bool
    is_foreign_key: bool
    caption: str | None
    description: str | None


class SchemaRelationshipResponse(BaseModel):
    source_column: str
    target_schema: str
    target_table: str
    target_column: str
    constraint_name: str | None


class SchemaObjectResponse(BaseModel):
    id: UUID
    schema_name: str
    object_name: str
    object_type: str
    description: str | None
    indexes: list[dict[str, object]]
    discovered_at: datetime
    columns: list[SchemaColumnResponse]
    relationships: list[SchemaRelationshipResponse]


class SchemaPageResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SchemaObjectResponse]


class SchemaDescriptionWrite(BaseModel):
    description: str | None = Field(default=None, max_length=5000)


class SchemaRefreshRequest(BaseModel):
    database_id: UUID


class SchemaRefreshResponse(BaseModel):
    database_id: UUID
    objects_discovered: int
    columns_discovered: int
    relationships_discovered: int
    captions_applied: int


def _validate_mapping_name(value: str, label: str) -> None:
    if (
        not value
        or not value.strip()
        or len(value) > 256
        or any(token in value for token in (";", "--", "/*", "*/", "'", '"', "[", "]", "\n", "\r"))
    ):
        raise ValueError(f"{label} must be an identifier, not a SQL fragment")
    if not re.fullmatch(r"[\w$ #&().,-]+", value, flags=re.UNICODE):
        raise ValueError(f"{label} contains unsupported identifier characters")
