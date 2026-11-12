from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.core.crypto import CredentialEncryptionError, CredentialVault
from app.database.schema_discovery import discover_sqlserver_schema
from app.database.session import get_db
from app.database.sqlserver import SqlServerOperationError, SqlServerTarget
from app.models.erp import (
    SchemaColumn,
    SchemaObject,
    SchemaRelationship,
)
from app.models.user import User
from app.schemas.erp import (
    SchemaColumnResponse,
    SchemaDescriptionWrite,
    SchemaObjectResponse,
    SchemaPageResponse,
    SchemaRefreshRequest,
    SchemaRefreshResponse,
    SchemaRelationshipResponse,
)
from app.services.database_access import get_connection_for_user, require_admin
from app.services.schema_snapshot import persist_schema_snapshot

router = APIRouter(prefix="/schema", tags=["database schema"])


@router.post("/refresh", response_model=SchemaRefreshResponse)
def refresh_schema(
    payload: SchemaRefreshRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SchemaRefreshResponse:
    connection = get_connection_for_user(db, user, payload.database_id, require_manage=True)
    if not connection.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "This database connection is disabled")
    credentials = None
    if connection.authentication_type == "sql_server":
        if not connection.credentials_encrypted:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Stored connection credentials are unavailable"
            )
        try:
            credentials = CredentialVault(settings).decrypt(connection.credentials_encrypted)
        except CredentialEncryptionError:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Stored connection credentials cannot be decrypted; check ENCRYPTION_KEY",
            ) from None
    try:
        snapshot = discover_sqlserver_schema(
            SqlServerTarget(
                connection.server, connection.database_name, connection.authentication_type
            ),
            credentials,
            connection.erp_version,
            settings,
        )
    except SqlServerOperationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    object_count, column_count, relationship_count = persist_schema_snapshot(
        db, connection, snapshot
    )
    connection.last_schema_refresh_at = datetime.now(UTC)
    connection.connection_status = "connected"
    connection.last_tested_at = connection.last_schema_refresh_at
    db.commit()
    return SchemaRefreshResponse(
        database_id=connection.id,
        objects_discovered=object_count,
        columns_discovered=column_count,
        relationships_discovered=relationship_count,
        captions_applied=snapshot.captions_applied,
    )


@router.get("/{database_id}", response_model=SchemaPageResponse)
def get_database_schema(
    database_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    search: str | None = Query(default=None, max_length=128),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SchemaPageResponse:
    get_connection_for_user(db, user, database_id)
    query = select(SchemaObject).where(SchemaObject.database_connection_id == database_id)
    count_query = (
        select(func.count())
        .select_from(SchemaObject)
        .where(SchemaObject.database_connection_id == database_id)
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.where(
            SchemaObject.object_name.ilike(pattern) | SchemaObject.schema_name.ilike(pattern)
        )
        count_query = count_query.where(
            SchemaObject.object_name.ilike(pattern) | SchemaObject.schema_name.ilike(pattern)
        )
    total = int(db.scalar(count_query) or 0)
    objects = list(
        db.scalars(
            query.order_by(SchemaObject.schema_name, SchemaObject.object_name)
            .offset(offset)
            .limit(limit)
        )
    )
    object_ids = [item.id for item in objects]
    columns_by_object: dict[UUID, list[SchemaColumn]] = {object_id: [] for object_id in object_ids}
    relationships_by_object: dict[UUID, list[SchemaRelationship]] = {
        object_id: [] for object_id in object_ids
    }
    if object_ids:
        for column in db.scalars(
            select(SchemaColumn)
            .where(SchemaColumn.schema_object_id.in_(object_ids))
            .order_by(SchemaColumn.schema_object_id, SchemaColumn.ordinal_position)
        ):
            columns_by_object[column.schema_object_id].append(column)
        for relationship in db.scalars(
            select(SchemaRelationship)
            .where(SchemaRelationship.source_object_id.in_(object_ids))
            .order_by(SchemaRelationship.source_object_id, SchemaRelationship.source_column)
        ):
            relationships_by_object[relationship.source_object_id].append(relationship)
    items = [
        SchemaObjectResponse(
            id=item.id,
            schema_name=item.schema_name,
            object_name=item.object_name,
            object_type=item.object_type,
            description=item.description,
            indexes=item.indexes,
            discovered_at=item.discovered_at,
            columns=[
                SchemaColumnResponse.model_validate(column) for column in columns_by_object[item.id]
            ],
            relationships=[
                SchemaRelationshipResponse(
                    source_column=relationship.source_column,
                    target_schema=relationship.target_schema,
                    target_table=relationship.target_table,
                    target_column=relationship.target_column,
                    constraint_name=relationship.constraint_name,
                )
                for relationship in relationships_by_object[item.id]
            ],
        )
        for item in objects
    ]
    return SchemaPageResponse(total=total, offset=offset, limit=limit, items=items)


@router.put("/{database_id}/objects/{object_id}", response_model=SchemaObjectResponse)
def update_schema_object_description(
    database_id: UUID,
    object_id: UUID,
    payload: SchemaDescriptionWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SchemaObjectResponse:
    require_admin(user)
    get_connection_for_user(db, user, database_id)
    item = db.get(SchemaObject, object_id)
    if item is None or item.database_connection_id != database_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schema object not found")
    item.description = payload.description.strip() if payload.description else None
    db.commit()
    return _object_response(db, item)


@router.put("/{database_id}/columns/{column_id}", response_model=SchemaColumnResponse)
def update_schema_column_description(
    database_id: UUID,
    column_id: UUID,
    payload: SchemaDescriptionWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SchemaColumnResponse:
    require_admin(user)
    get_connection_for_user(db, user, database_id)
    column = db.get(SchemaColumn, column_id)
    parent = db.get(SchemaObject, column.schema_object_id) if column else None
    if parent is None or parent.database_connection_id != database_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schema column not found")
    column.description = payload.description.strip() if payload.description else None
    db.commit()
    return SchemaColumnResponse.model_validate(column)


def _object_response(db: Session, item: SchemaObject) -> SchemaObjectResponse:
    columns = db.scalars(
        select(SchemaColumn)
        .where(SchemaColumn.schema_object_id == item.id)
        .order_by(SchemaColumn.ordinal_position)
    )
    relationships = db.scalars(
        select(SchemaRelationship)
        .where(SchemaRelationship.source_object_id == item.id)
        .order_by(SchemaRelationship.source_column)
    )
    return SchemaObjectResponse(
        id=item.id,
        schema_name=item.schema_name,
        object_name=item.object_name,
        object_type=item.object_type,
        description=item.description,
        indexes=item.indexes,
        discovered_at=item.discovered_at,
        columns=[SchemaColumnResponse.model_validate(column) for column in columns],
        relationships=[
            SchemaRelationshipResponse(
                source_column=relationship.source_column,
                target_schema=relationship.target_schema,
                target_table=relationship.target_table,
                target_column=relationship.target_column,
                constraint_name=relationship.constraint_name,
            )
            for relationship in relationships
        ],
    )
