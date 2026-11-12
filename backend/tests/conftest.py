import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models.user import User, UserRole


@pytest.fixture
def test_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestingSession
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def test_settings():
    return Settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key=SecretStr("test-only-jwt-secret-key-that-is-long-enough"),
        encryption_key=SecretStr("test-only-encryption-master-secret-value-123456789"),
    )


@pytest.fixture
def client(test_session_factory, test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    with test_session_factory() as db:
        db.add(
            User(
                email="admin@example.com",
                full_name="Test Admin",
                password_hash=hash_password("correct horse battery staple"),
                role=UserRole.ADMIN.value,
            )
        )
        db.commit()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
