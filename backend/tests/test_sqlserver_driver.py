from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.database.sqlserver import SqlServerTarget, build_sqlserver_url


def test_sql_server_url_uses_encoded_secret_and_required_encryption_options():
    settings = Settings(
        _env_file=None,
        app_env="test",
        sqlserver_trust_server_certificate=False,
    )
    password = "A-secret@with:/symbols?"
    url = build_sqlserver_url(
        SqlServerTarget("sql.internal,1433", "NAV Production", "sql_server"),
        {"username": "report reader", "password": password},
        settings,
    )
    assert url.password == password
    assert url.query["driver"] == "ODBC Driver 18 for SQL Server"
    assert url.query["Encrypt"] == "yes"
    assert url.query["TrustServerCertificate"] == "no"
    assert password not in url.render_as_string(hide_password=True)


def test_windows_authentication_uses_trusted_connection_without_credentials():
    url = build_sqlserver_url(
        SqlServerTarget("sql.internal", "BC_Production", "windows"),
        credentials=None,
        settings=Settings(_env_file=None, app_env="test"),
    )
    assert url.username is None
    assert url.password is None
    assert url.query["Trusted_Connection"] == "yes"


def test_encryption_key_is_required_in_production():
    try:
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key=SecretStr("production-jwt-secret-long-enough-123456"),
        )
    except ValidationError as exc:
        assert "ENCRYPTION_KEY" in str(exc)
    else:
        raise AssertionError("production settings must reject a missing encryption key")

    Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key=SecretStr("production-jwt-secret-long-enough-123456"),
        encryption_key=SecretStr("production-encryption-master-key-long-enough-123"),
    )
