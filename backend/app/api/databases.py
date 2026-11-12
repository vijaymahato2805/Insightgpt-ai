import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.core.crypto import CredentialEncryptionError, CredentialVault
from app.database.session import get_db
from app.database.sqlserver import SqlServerTarget, test_sqlserver_connection
from app.models.erp import (
    BusinessDictionaryEntry,
    CompanyMapping,
    DatabaseConnection,
    SchemaColumn,
    SchemaObject,
    SchemaRelationship,
    UserDatabaseAccess,
)
from app.models.user import User
from app.schemas.erp import (
    DatabaseAccessList,
    DatabaseAccessResponse,
    DatabaseAccessWrite,
    DatabaseConnectionList,
    DatabaseConnectionResponse,
    DatabaseConnectionUpdate,
    DatabaseConnectionWrite,
    DatabaseTestRequest,
    DatabaseTestResponse,
)
from app.services.database_access import (
    accessible_connections,
    get_connection_for_user,
    require_admin,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/databases", tags=["SQL Server databases"])


def _credentials_from_input(payload: DatabaseConnectionWrite) -> dict[str, str] | None:
    if payload.authentication_type.value == "windows":
        return None
    password = payload.password.get_secret_value() if payload.password else ""
    if not payload.username or not password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "username and password are required for SQL Server authentication",
        )
    return {"username": payload.username, "password": password}


def _stored_credentials(
    connection: DatabaseConnection, settings: Settings
) -> dict[str, str] | None:
    if connection.authentication_type == "windows":
        return None
    if not connection.credentials_encrypted:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Stored connection credentials are unavailable"
        )
    try:
        return CredentialVault(settings).decrypt(connection.credentials_encrypted)
    except CredentialEncryptionError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stored connection credentials cannot be decrypted; check ENCRYPTION_KEY",
        ) from None


def _target(connection: DatabaseConnection) -> SqlServerTarget:
    return SqlServerTarget(
        server=connection.server,
        database_name=connection.database_name,
        authentication_type=connection.authentication_type,
    )


def _check_result_for_connection(
    connection: DatabaseConnection,
    credentials: dict[str, str] | None,
    db: Session,
    settings: Settings,
) -> DatabaseTestResponse:
    result = test_sqlserver_connection(_target(connection), credentials, settings)
    connection.connection_status = "connected" if result.success else "error"
    connection.last_tested_at = datetime.now(UTC)
    db.commit()
    return DatabaseTestResponse(success=result.success, message=result.message)


@router.get("", response_model=DatabaseConnectionList)
def list_databases(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DatabaseConnectionList:
    return DatabaseConnectionList(
        items=[
            DatabaseConnectionResponse.model_validate(item)
            for item in accessible_connections(db, user)
        ]
    )


@router.post("", response_model=DatabaseConnectionResponse, status_code=status.HTTP_201_CREATED)
def create_database(
    payload: DatabaseConnectionWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DatabaseConnectionResponse:
    require_admin(user)
    credentials = _credentials_from_input(payload)
    encrypted = None
    if credentials:
        try:
            encrypted = CredentialVault(settings).encrypt(credentials)
        except CredentialEncryptionError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None

    connection = DatabaseConnection(
        connection_name=payload.connection_name,
        company_name=payload.company_name,
        server=payload.server,
        database_name=payload.database,
        authentication_type=payload.authentication_type.value,
        erp_version=payload.erp_version.value,
        enabled=payload.enabled,
        credentials_encrypted=encrypted,
        created_by=user.id,
    )
    db.add(connection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A connection with that name already exists"
        ) from None
    db.refresh(connection)
    return DatabaseConnectionResponse.model_validate(connection)


@router.put("/{database_id}", response_model=DatabaseConnectionResponse)
def update_database(
    database_id: UUID,
    payload: DatabaseConnectionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DatabaseConnectionResponse:
    require_admin(user)
    connection = db.get(DatabaseConnection, database_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    changes = payload.model_dump(exclude_unset=True, exclude={"password"})
    for field_name in ("authentication_type", "erp_version"):
        if changes.get(field_name) is not None:
            changes[field_name] = changes[field_name].value
    old_target = (connection.server, connection.database_name)
    for field_name in (
        "connection_name",
        "company_name",
        "server",
        "database",
        "erp_version",
        "enabled",
    ):
        if field_name in changes:
            setattr(
                connection,
                "database_name" if field_name == "database" else field_name,
                changes[field_name],
            )

    next_auth = changes.get("authentication_type", connection.authentication_type)
    if next_auth == "windows":
        if payload.username or payload.password:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Windows Authentication does not accept username or password fields",
            )
        connection.credentials_encrypted = None
    else:
        stored = {}
        if connection.authentication_type == "sql_server" and connection.credentials_encrypted:
            stored = _stored_credentials(connection, settings) or {}
        username = payload.username if payload.username is not None else stored.get("username", "")
        password = (
            payload.password.get_secret_value() if payload.password else stored.get("password", "")
        )
        if not username or not password:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "SQL Server authentication requires username and password",
            )
        try:
            connection.credentials_encrypted = CredentialVault(settings).encrypt(
                {"username": username, "password": password}
            )
        except CredentialEncryptionError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    connection.authentication_type = next_auth
    connection.connection_status = "untested"
    connection.last_tested_at = None
    if old_target != (connection.server, connection.database_name):
        _clear_schema_snapshot(db, connection.id)
        connection.last_schema_refresh_at = None
        for mapping in db.scalars(
            select(CompanyMapping).where(
                CompanyMapping.database_connection_id == connection.id,
                CompanyMapping.is_auto_generated.is_(True),
            )
        ):
            mapping.table_mappings = {}
            mapping.field_mappings = {}
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A connection with that name already exists"
        ) from None
    db.refresh(connection)
    return DatabaseConnectionResponse.model_validate(connection)


@router.delete("/{database_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_database(
    database_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_admin(user)
    connection = db.get(DatabaseConnection, database_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    _clear_schema_snapshot(db, database_id)
    db.execute(
        delete(BusinessDictionaryEntry).where(
            BusinessDictionaryEntry.database_connection_id == database_id
        )
    )
    db.execute(delete(CompanyMapping).where(CompanyMapping.database_connection_id == database_id))
    db.execute(
        delete(UserDatabaseAccess).where(UserDatabaseAccess.database_connection_id == database_id)
    )
    db.delete(connection)
    db.commit()


@router.post("/test", response_model=DatabaseTestResponse)
def test_database(
    payload: DatabaseTestRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DatabaseTestResponse:
    if payload.connection is not None:
        require_admin(user)
        source = payload.connection
        credentials = _credentials_from_input(source)
        target = SqlServerTarget(source.server, source.database, source.authentication_type.value)
        result = test_sqlserver_connection(target, credentials, settings)
        return DatabaseTestResponse(success=result.success, message=result.message)

    connection = get_connection_for_user(db, user, payload.database_id, require_manage=True)  # type: ignore[arg-type]
    credentials = _stored_credentials(connection, settings)
    return _check_result_for_connection(connection, credentials, db, settings)


@router.get("/{database_id}/access", response_model=DatabaseAccessList)
def list_database_access(
    database_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DatabaseAccessList:
    require_admin(user)
    if db.get(DatabaseConnection, database_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    rows = db.scalars(
        select(UserDatabaseAccess).where(UserDatabaseAccess.database_connection_id == database_id)
    )
    return DatabaseAccessList(items=[DatabaseAccessResponse.model_validate(row) for row in rows])


@router.put("/{database_id}/access/{user_id}", response_model=DatabaseAccessResponse)
def grant_database_access(
    database_id: UUID,
    user_id: UUID,
    payload: DatabaseAccessWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DatabaseAccessResponse:
    require_admin(user)
    if db.get(DatabaseConnection, database_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    access = db.get(UserDatabaseAccess, (user_id, database_id))
    if access is None:
        access = UserDatabaseAccess(
            user_id=user_id,
            database_connection_id=database_id,
            permission=payload.permission.value,
            granted_by=user.id,
        )
        db.add(access)
    else:
        access.permission = payload.permission.value
        access.granted_by = user.id
    db.commit()
    db.refresh(access)
    return DatabaseAccessResponse.model_validate(access)


@router.delete("/{database_id}/access/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_database_access(
    database_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_admin(user)
    access = db.get(UserDatabaseAccess, (user_id, database_id))
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database access grant not found")
    db.delete(access)
    db.commit()


def _clear_schema_snapshot(db: Session, database_id: UUID) -> None:
    object_ids = select(SchemaObject.id).where(SchemaObject.database_connection_id == database_id)
    db.execute(
        delete(SchemaRelationship).where(SchemaRelationship.source_object_id.in_(object_ids))
    )
    db.execute(delete(SchemaColumn).where(SchemaColumn.schema_object_id.in_(object_ids)))
    db.execute(delete(SchemaObject).where(SchemaObject.database_connection_id == database_id))
