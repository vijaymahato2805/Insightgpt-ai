import logging
from dataclasses import dataclass
from typing import Any

import pyodbc
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SqlServerOperationError(RuntimeError):
    """A safe, user-facing error for SQL Server connectivity or metadata failures."""


@dataclass(frozen=True)
class SqlServerTarget:
    server: str
    database_name: str
    authentication_type: str


@dataclass(frozen=True)
class SqlServerTestResult:
    success: bool
    message: str


def build_sqlserver_url(
    target: SqlServerTarget,
    credentials: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> URL:
    config = settings or get_settings()
    query: dict[str, str] = {
        "driver": config.sqlserver_odbc_driver,
        "Encrypt": "yes",
        "TrustServerCertificate": "yes" if config.sqlserver_trust_server_certificate else "no",
    }
    username = None
    password = None
    if target.authentication_type == "windows":
        query["Trusted_Connection"] = "yes"
    elif target.authentication_type == "sql_server":
        if not credentials or not credentials.get("username") or not credentials.get("password"):
            raise SqlServerOperationError("SQL Server credentials are not configured")
        username = credentials["username"]
        password = credentials["password"]
    else:
        raise SqlServerOperationError("Unsupported SQL Server authentication type")

    return URL.create(
        "mssql+pyodbc",
        username=username,
        password=password,
        host=target.server,
        database=target.database_name,
        query=query,
    )


def create_sqlserver_engine(
    target: SqlServerTarget,
    credentials: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> Engine:
    config = settings or get_settings()
    url = build_sqlserver_url(target, credentials, config)
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"timeout": config.sqlserver_connection_timeout_seconds},
    )


def test_sqlserver_connection(
    target: SqlServerTarget,
    credentials: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> SqlServerTestResult:
    engine: Engine | None = None
    try:
        engine = create_sqlserver_engine(target, credentials, settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return SqlServerTestResult(success=True, message="Connection succeeded")
    except (SQLAlchemyError, pyodbc.Error, OSError, TimeoutError):
        logger.warning("SQL Server connection test failed for configured target")
        return SqlServerTestResult(
            success=False, message="Connection failed; check server and credentials"
        )
    except Exception:  # noqa: BLE001 - driver loading can fail with platform-specific exception types.
        # Driver initialization can fail before SQLAlchemy wraps the error; never return it to clients.
        logger.warning("SQL Server connection setup failed")
        return SqlServerTestResult(
            success=False, message="Connection failed; check server and driver setup"
        )
    finally:
        if engine is not None:
            engine.dispose()


def get_engine_from_connection(
    server: str,
    database_name: str,
    authentication_type: str,
    credentials: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> Engine:
    """Build an engine from persisted, decrypted connection properties."""
    return create_sqlserver_engine(
        SqlServerTarget(server, database_name, authentication_type), credentials, settings
    )


def normalize_metadata_name(value: Any) -> str:
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())
