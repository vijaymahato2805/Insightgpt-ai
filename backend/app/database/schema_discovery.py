import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.database.sqlserver import (
    SqlServerOperationError,
    SqlServerTarget,
    create_sqlserver_engine,
    normalize_metadata_name,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredColumn:
    name: str
    ordinal_position: int
    data_type: str
    nullable: bool
    default_value: str | None
    is_primary_key: bool
    is_foreign_key: bool
    caption: str | None = None


@dataclass(frozen=True)
class DiscoveredRelationship:
    source_column: str
    target_schema: str
    target_table: str
    target_column: str
    constraint_name: str | None


@dataclass(frozen=True)
class DiscoveredObject:
    schema_name: str
    object_name: str
    object_type: str
    columns: list[DiscoveredColumn] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[DiscoveredRelationship] = field(default_factory=list)


@dataclass(frozen=True)
class SchemaDiscoveryResult:
    objects: list[DiscoveredObject]
    captions_applied: int


def discover_sqlserver_schema(
    target: SqlServerTarget,
    credentials: dict[str, str] | None = None,
    erp_version: str = "sql_server",
    settings: Settings | None = None,
) -> SchemaDiscoveryResult:
    config = settings or get_settings()
    engine = create_sqlserver_engine(target, credentials, config)
    try:
        result = inspect_sqlserver_engine(engine, erp_version, config)
        return result
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning("SQL Server schema discovery failed")
        raise SqlServerOperationError(
            "Schema discovery failed; verify database access and metadata permissions"
        ) from exc
    except Exception as exc:
        logger.warning("SQL Server schema discovery setup failed")
        raise SqlServerOperationError(
            "Schema discovery failed; verify the ODBC driver and database setup"
        ) from exc
    finally:
        engine.dispose()


def inspect_sqlserver_engine(
    engine: Engine,
    erp_version: str,
    settings: Settings | None = None,
) -> SchemaDiscoveryResult:
    config = settings or get_settings()
    inspector = inspect(engine)
    names: list[tuple[str, str, str]] = []
    schemas = [
        schema
        for schema in inspector.get_schema_names()
        if schema.casefold() not in {"sys", "information_schema"}
    ]
    if not schemas:
        schemas = [None]
    for schema in schemas:
        schema_name = schema or "dbo"
        names.extend(
            (schema_name, name, "table") for name in inspector.get_table_names(schema=schema)
        )
        names.extend(
            (schema_name, name, "view") for name in inspector.get_view_names(schema=schema)
        )
    if len(names) > config.schema_discovery_max_objects:
        raise SqlServerOperationError(
            f"Schema contains more than the configured limit of {config.schema_discovery_max_objects} objects"
        )

    captions = (
        read_nav_field_captions(engine, inspector, names)
        if erp_version in {"nav_2013_r2", "nav_2018", "business_central"}
        else {}
    )
    objects: list[DiscoveredObject] = []
    for schema_name, object_name, object_type in names:
        column_details = inspector.get_columns(object_name, schema=schema_name)
        primary_key_names = set(
            (inspector.get_pk_constraint(object_name, schema=schema_name) or {}).get(
                "constrained_columns"
            )
            or []
        )
        foreign_keys = inspector.get_foreign_keys(object_name, schema=schema_name)
        foreign_columns = {
            column for key in foreign_keys for column in (key.get("constrained_columns") or [])
        }
        columns: list[DiscoveredColumn] = []
        for ordinal, column in enumerate(column_details, start=1):
            column_name = str(column["name"])
            columns.append(
                DiscoveredColumn(
                    name=column_name,
                    ordinal_position=int(column.get("ordinal_position") or ordinal),
                    data_type=str(column.get("type") or "unknown"),
                    nullable=bool(column.get("nullable", True)),
                    default_value=str(column["default"])
                    if column.get("default") is not None
                    else None,
                    is_primary_key=column_name in primary_key_names,
                    is_foreign_key=column_name in foreign_columns,
                    caption=captions.get((schema_name, object_name, column_name)),
                )
            )
        relationships: list[DiscoveredRelationship] = []
        for key in foreign_keys:
            remote_schema = str(key.get("referred_schema") or schema_name)
            remote_table = str(key.get("referred_table") or "")
            local_columns = key.get("constrained_columns") or []
            remote_columns = key.get("referred_columns") or []
            for local, remote in zip(local_columns, remote_columns, strict=False):
                relationships.append(
                    DiscoveredRelationship(
                        source_column=str(local),
                        target_schema=remote_schema,
                        target_table=remote_table,
                        target_column=str(remote),
                        constraint_name=str(key["name"]) if key.get("name") else None,
                    )
                )
        indexes = []
        for index in inspector.get_indexes(object_name, schema=schema_name):
            indexes.append(
                {
                    "name": str(index["name"]) if index.get("name") else None,
                    "columns": [str(name) for name in (index.get("column_names") or []) if name],
                    "unique": bool(index.get("unique", False)),
                }
            )
        objects.append(
            DiscoveredObject(
                schema_name=schema_name,
                object_name=object_name,
                object_type=object_type,
                columns=columns,
                indexes=indexes,
                relationships=relationships,
            )
        )
    return SchemaDiscoveryResult(objects=objects, captions_applied=len(captions))


def read_nav_field_captions(
    engine: Engine,
    inspector: Any,
    discovered_names: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], str]:
    """Read optional NAV/BC Field and Object metadata without assuming those tables exist."""
    field_ref = _find_metadata_table(inspector, {"field", "fields", "fieldmetadata"})
    if field_ref is None:
        return {}
    field_schema, field_name = field_ref
    try:
        metadata = MetaData()
        field_table = Table(field_name, metadata, schema=field_schema, autoload_with=engine)
        columns_by_normalized = {
            normalize_metadata_name(column.name): column for column in field_table.columns
        }
        table_no = _find_column(columns_by_normalized, {"tableno", "tableid", "objectid"})
        table_name = _find_column(columns_by_normalized, {"tablename", "objectname"})
        field_name_column = _find_column(columns_by_normalized, {"fieldname", "name"})
        caption_column = _find_column(columns_by_normalized, {"caption", "fieldcaption"})
        if (
            caption_column is None
            or field_name_column is None
            or (table_no is None and table_name is None)
        ):
            return {}

        object_names: dict[str, str] = {}
        if table_no is not None and table_name is None:
            object_ref = _find_metadata_table(inspector, {"object", "objects", "objectmetadata"})
            if object_ref:
                object_schema, object_table_name = object_ref
                object_table = Table(
                    object_table_name, MetaData(), schema=object_schema, autoload_with=engine
                )
                object_columns = {
                    normalize_metadata_name(column.name): column for column in object_table.columns
                }
                object_id = _find_column(object_columns, {"id", "objectid", "no"})
                object_name_column = _find_column(
                    object_columns, {"name", "objectname", "tablename"}
                )
                if object_id is not None and object_name_column is not None:
                    with engine.connect() as connection:
                        rows = connection.execute(select(object_id, object_name_column)).all()
                    object_names = {
                        str(row[0]): str(row[1]) for row in rows if row[0] is not None and row[1]
                    }

        selected = [field_name_column, caption_column]
        if table_no is not None:
            selected.append(table_no)
        if table_name is not None:
            selected.append(table_name)
        with engine.connect() as connection:
            rows = connection.execute(select(*selected)).all()
    except (SQLAlchemyError, KeyError, ValueError):
        logger.info("Optional NAV/Business Central caption metadata was unavailable")
        return {}

    physical_by_logical: dict[str, list[tuple[str, str]]] = {}
    for schema_name, object_name, object_type in discovered_names:
        if object_type != "table":
            continue
        logical_name = object_name.rsplit("$", 1)[-1] if "$" in object_name else object_name
        physical_by_logical.setdefault(normalize_metadata_name(logical_name), []).append(
            (schema_name, object_name)
        )

    captions: dict[tuple[str, str, str], str] = {}
    for row in rows:
        values = dict(zip([column.name for column in selected], row, strict=False))
        logical_table = (
            str(values.get(table_name.name))
            if table_name is not None and values.get(table_name.name)
            else None
        )
        if logical_table is None and table_no is not None and values.get(table_no.name) is not None:
            logical_table = object_names.get(str(values[table_no.name]))
        field = str(values.get(field_name_column.name) or "")
        caption = str(values.get(caption_column.name) or "").strip()
        if not logical_table or not field or not caption:
            continue
        matching_tables = physical_by_logical.get(normalize_metadata_name(logical_table), [])
        for schema_name, object_name in matching_tables:
            captions[(schema_name, object_name, field)] = caption
    return captions


def _find_metadata_table(inspector: Any, accepted_names: set[str]) -> tuple[str | None, str] | None:
    for schema in inspector.get_schema_names():
        for name in inspector.get_table_names(schema=schema):
            if normalize_metadata_name(name) in accepted_names:
                return schema, name
    for name in inspector.get_table_names():
        if normalize_metadata_name(name) in accepted_names:
            return None, name
    return None


def _find_column(columns: dict[str, Any], accepted_names: set[str]) -> Any | None:
    return next((column for key, column in columns.items() if key in accepted_names), None)
