from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, MessageResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect")

    settings = get_settings()
    token = create_access_token(user.id, user.token_version, settings)
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=settings.jwt_access_token_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api",
    )
    return AuthResponse(user=UserResponse.model_validate(user))


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    user.token_version += 1
    db.commit()
    response.delete_cookie("access_token", path="/api", httponly=True, samesite="lax")
    return MessageResponse(message="Signed out")


@router.get("/me", response_model=UserResponse)
def current_user(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)
