from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "InsightGPT AI"
    database_url: str = "postgresql+psycopg://insightgpt:local-dev-only@localhost:5432/insightgpt"
    jwt_secret_key: SecretStr = SecretStr("local-only-change-this-secret-key-before-deploying")
    encryption_key: SecretStr | None = None
    jwt_access_token_minutes: int = Field(default=60, ge=5, le=1440)
    cookie_secure: bool = False
    frontend_origins: str = "http://localhost:5173"

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:5173"
    openrouter_app_name: str = "InsightGPT AI"
    sql_model: str | None = None
    reasoning_model: str | None = None
    fast_model: str | None = None
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    sqlserver_odbc_driver: str = "ODBC Driver 18 for SQL Server"
    sqlserver_trust_server_certificate: bool = False
    sqlserver_connection_timeout_seconds: int = Field(default=8, ge=2, le=60)
    schema_discovery_max_objects: int = Field(default=5000, ge=1, le=100000)
    sql_query_timeout_seconds: int = Field(default=30, ge=2, le=300)
    sql_max_result_rows: int = Field(default=500, ge=1, le=5000)
    sql_max_ast_nodes: int = Field(default=1200, ge=50, le=10000)
    sql_max_joins: int = Field(default=8, ge=0, le=32)

    @model_validator(mode="after")
    def validate_encryption_key(self) -> "Settings":
        secret = self.encryption_key.get_secret_value() if self.encryption_key else ""
        if secret and len(secret) < 32:
            raise ValueError("ENCRYPTION_KEY must contain at least 32 characters")
        if self.app_env == "production" and not secret:
            raise ValueError("ENCRYPTION_KEY must be configured in production")
        return self

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr, info):  # type: ignore[no-untyped-def]
        secret = value.get_secret_value()
        if info.data.get("app_env") == "production":
            if len(secret) < 32:
                raise ValueError("JWT_SECRET_KEY must contain at least 32 characters in production")
            if secret == "local-only-change-this-secret-key-before-deploying":
                raise ValueError("JWT_SECRET_KEY must be replaced before production deployment")
        return value

    @field_validator("openrouter_base_url")
    @classmethod
    def validate_openrouter_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OPENROUTER_BASE_URL must be an absolute HTTP(S) URL")
        return value.rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def model_registry_path(self) -> Path:
        local_path = PROJECT_ROOT / "config" / "model_registry.json"
        container_path = Path("/app/config/model_registry.json")
        return local_path if local_path.is_file() else container_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
