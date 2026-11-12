from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.session import get_db
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    if token is None and credentials is not None:
        token = credentials.credentials
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
        token_version = int(payload["ver"])
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from None

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.token_version != token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return user


def require_roles(*allowed: UserRole) -> Callable:
    allowed_values = {role.value for role in allowed}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_values:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return dependency
