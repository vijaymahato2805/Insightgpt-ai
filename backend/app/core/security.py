from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, password_digest: str) -> bool:
    return password_hash.verify(password, password_digest)


def create_access_token(user_id: UUID, token_version: int, settings: Settings | None = None) -> str:
    config = settings or get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=config.jwt_access_token_minutes)
    payload = {"sub": str(user_id), "ver": token_version, "iat": now, "exp": expires}
    return jwt.encode(payload, config.jwt_secret_key.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings | None = None) -> dict:
    config = settings or get_settings()
    return jwt.decode(
        token,
        config.jwt_secret_key.get_secret_value(),
        algorithms=[ALGORITHM],
        options={"require": ["sub", "ver", "exp"]},
    )
