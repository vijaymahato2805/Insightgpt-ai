import re
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.schema_discovery import DiscoveredObject, SchemaDiscoveryResult
from app.models.erp import (
    CompanyMapping,
    DatabaseConnection,
    SchemaColumn,
    SchemaObject,
    SchemaRelationship,
)

CANONICAL_TABLES = {
    "sales_header": {"salesheader"},
    "sales_line": {"salesline"},
    "item_ledger_entry": {"itemledgerentry"},
    "value_entry": {"valueentry"},
    "customer": {"customer"},
    "item": {"item"},
    "location": {"location"},
    "vendor": {"vendor"},
}


def persist_schema_snapshot(
    db: Session,
    connection: DatabaseConnection,
    result: SchemaDiscoveryResult,
) -> tuple[int, int, int]:
    existing = list(
        db.scalars(select(SchemaObject).where(SchemaObject.database_connection_id == connection.id))
    )
    existing_by_key = {
        (obj.schema_name.casefold(), obj.object_name.casefold()): obj for obj in existing
    }
    object_ids = [obj.id for obj in existing]
    old_descriptions: dict[tuple[str, str, str], str | None] = {}
    if object_ids:
        old_columns = db.scalars(
            select(SchemaColumn).where(SchemaColumn.schema_object_id.in_(object_ids))
        )
        old_objects_by_id = {obj.id: obj for obj in existing}
        for column in old_columns:
            parent = old_objects_by_id.get(column.schema_object_id)
            if parent:
                old_descriptions[
                    (
                        parent.schema_name.casefold(),
                        parent.object_name.casefold(),
                        column.column_name.casefold(),
                    )
                ] = column.description
        db.execute(
            delete(SchemaRelationship).where(SchemaRelationship.source_object_id.in_(object_ids))
        )
        db.execute(delete(SchemaColumn).where(SchemaColumn.schema_object_id.in_(object_ids)))

    now = datetime.now(UTC)
    object_count = 0
    column_count = 0
    relationship_count = 0
    for discovered in result.objects:
        key = (discovered.schema_name.casefold(), discovered.object_name.casefold())
        schema_object = existing_by_key.pop(key, None)
        if schema_object is None:
            schema_object = SchemaObject(
                database_connection_id=connection.id,
                schema_name=discovered.schema_name,
                object_name=discovered.object_name,
                object_type=discovered.object_type,
                description=None,
                indexes=discovered.indexes,
                discovered_at=now,
            )
            db.add(schema_object)
            db.flush()
        else:
            schema_object.object_type = discovered.object_type
            schema_object.indexes = discovered.indexes
            schema_object.discovered_at = now
        object_count += 1
        for column in discovered.columns:
            db.add(
                SchemaColumn(
                    schema_object_id=schema_object.id,
                    column_name=column.name,
                    ordinal_position=column.ordinal_position,
                    data_type=column.data_type,
                    nullable=column.nullable,
                    default_value=column.default_value,
                    is_primary_key=column.is_primary_key,
                    is_foreign_key=column.is_foreign_key,
                    caption=column.caption,
                    description=old_descriptions.get((key[0], key[1], column.name.casefold())),
                )
            )
            column_count += 1
        for relationship in discovered.relationships:
            db.add(
                SchemaRelationship(
                    source_object_id=schema_object.id,
                    source_column=relationship.source_column,
                    target_schema=relationship.target_schema,
                    target_table=relationship.target_table,
                    target_column=relationship.target_column,
                    constraint_name=relationship.constraint_name,
                )
            )
            relationship_count += 1
    stale_ids = [obj.id for obj in existing_by_key.values()]
    if stale_ids:
        db.execute(
            delete(SchemaRelationship).where(SchemaRelationship.source_object_id.in_(stale_ids))
        )
        db.execute(delete(SchemaColumn).where(SchemaColumn.schema_object_id.in_(stale_ids)))
        db.execute(delete(SchemaObject).where(SchemaObject.id.in_(stale_ids)))
    db.flush()
    sync_auto_company_mappings(db, connection, result.objects)
    return object_count, column_count, relationship_count


def sync_auto_company_mappings(
    db: Session,
    connection: DatabaseConnection,
    objects: list[DiscoveredObject],
) -> None:
    inferred: dict[str, dict[str, str]] = {}
    for obj in objects:
        if obj.object_type != "table":
            continue
        if "$" in obj.object_name:
            company, logical_table = obj.object_name.rsplit("$", 1)
            if not company or not logical_table:
                continue
        elif connection.company_name:
            company, logical_table = connection.company_name, obj.object_name
        else:
            continue
        logical_key = _normalize_table(logical_table)
        canonical = next(
            (name for name, aliases in CANONICAL_TABLES.items() if logical_key in aliases), None
        )
        if canonical:
            inferred.setdefault(company, {})[canonical] = f"{obj.schema_name}.{obj.object_name}"

    existing = {
        item.company_name.casefold(): item
        for item in db.scalars(
            select(CompanyMapping).where(CompanyMapping.database_connection_id == connection.id)
        )
    }
    for company, table_mappings in inferred.items():
        mapping = existing.get(company.casefold())
        if mapping and not mapping.is_auto_generated:
            continue
        if mapping is None:
            mapping = CompanyMapping(
                database_connection_id=connection.id,
                company_name=company,
                erp_version=connection.erp_version,
                table_mappings=table_mappings,
                field_mappings={},
                is_auto_generated=True,
            )
            db.add(mapping)
        else:
            mapping.table_mappings = table_mappings
            mapping.erp_version = connection.erp_version
    db.flush()


def _normalize_table(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())
