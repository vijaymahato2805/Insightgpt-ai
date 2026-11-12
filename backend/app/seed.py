"""Create the optional first administrator from environment configuration."""

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.database.session import SessionLocal
from app.models.user import User, UserRole

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def seed_admin() -> None:
    settings = get_settings()
    email = (settings.bootstrap_admin_email or "").strip().lower()
    password = (
        settings.bootstrap_admin_password.get_secret_value()
        if settings.bootstrap_admin_password
        else ""
    )
    if not email and not password:
        logger.info("Bootstrap admin credentials are unset; skipping admin creation")
        return
    if not email or not password:
        raise RuntimeError("Set both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD")
    if len(password) < 12:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            logger.info("Bootstrap admin already exists; no account changes made")
            return
        user = User(
            email=email,
            full_name="InsightGPT Administrator",
            password_hash=hash_password(password),
            role=UserRole.SUPER_ADMIN.value,
        )
        db.add(user)
        db.commit()
        logger.info("Created bootstrap administrator %s", email)


if __name__ == "__main__":
    seed_admin()
