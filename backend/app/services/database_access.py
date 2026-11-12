from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.erp import DatabaseConnection, UserDatabaseAccess
from app.models.user import User, UserRole


def is_admin(user: User) -> bool:
    return user.role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}


def get_connection_for_user(
    db: Session,
    user: User,
    database_id: UUID,
    *,
    require_manage: bool = False,
) -> DatabaseConnection:
    connection = db.get(DatabaseConnection, database_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    if is_admin(user):
        return connection
    access = db.get(UserDatabaseAccess, (user.id, database_id))
    allowed = bool(access) and (not require_manage or access.permission == "manage")
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    return connection


def accessible_connections(db: Session, user: User) -> list[DatabaseConnection]:
    query = select(DatabaseConnection).order_by(DatabaseConnection.connection_name)
    if is_admin(user):
        return list(db.scalars(query))
    query = query.join(
        UserDatabaseAccess,
        UserDatabaseAccess.database_connection_id == DatabaseConnection.id,
    ).where(UserDatabaseAccess.user_id == user.id)
    return list(db.scalars(query))


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator permission required")
