from uuid import UUID

from fastapi.testclient import TestClient

import app.api.databases as database_api
from app.core.crypto import CredentialVault
from app.core.security import hash_password
from app.database.sqlserver import SqlServerTestResult
from app.main import app
from app.models.erp import DatabaseConnection
from app.models.user import User, UserRole


def _admin_login(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200


def _connection_payload(**overrides):
    payload = {
        "connection_name": "NAV reporting",
        "company_name": "Contoso",
        "server": "sql.example.internal",
        "database": "NAV_Production",
        "authentication_type": "sql_server",
        "username": "insight_reader",
        "password": "Never-return-this-password",
        "erp_version": "nav_2018",
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def _create_connection(client):
    response = client.post("/api/databases", json=_connection_payload())
    assert response.status_code == 201, response.text
    return response.json()


def test_connection_crud_encrypts_credentials_and_omits_them_from_responses(
    client, test_session_factory, test_settings, monkeypatch
):
    _admin_login(client)
    created = _create_connection(client)
    connection_id = created["id"]
    assert created["connection_status"] == "untested"
    assert created["has_credentials"] is True
    for secret_field in ("password", "username", "credentials_encrypted"):
        assert secret_field not in created

    with test_session_factory() as db:
        stored = db.get(DatabaseConnection, UUID(connection_id))
        assert stored is not None
        assert "Never-return-this-password" not in stored.credentials_encrypted
        assert CredentialVault(test_settings).decrypt(stored.credentials_encrypted) == {
            "username": "insight_reader",
            "password": "Never-return-this-password",
        }

    seen = {}

    def successful_test(target, credentials, settings):
        seen.update(target=target, credentials=credentials)
        return SqlServerTestResult(True, "Connection succeeded")

    monkeypatch.setattr(database_api, "test_sqlserver_connection", successful_test)
    tested = client.post("/api/databases/test", json={"database_id": connection_id})
    assert tested.status_code == 200
    assert tested.json() == {"success": True, "message": "Connection succeeded"}
    assert seen["credentials"]["password"] == "Never-return-this-password"
    assert "Never-return-this-password" not in tested.text

    updated = client.put(f"/api/databases/{connection_id}", json={"connection_name": "NAV reports"})
    assert updated.status_code == 200
    assert updated.json()["connection_name"] == "NAV reports"
    assert updated.json()["connection_status"] == "untested"
    assert "Never-return-this-password" not in updated.text

    listing = client.get("/api/databases")
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1
    assert "credentials_encrypted" not in listing.text


def test_connection_test_accepts_an_unsaved_configuration_without_echoing_secrets(
    client, monkeypatch
):
    _admin_login(client)
    monkeypatch.setattr(
        database_api,
        "test_sqlserver_connection",
        lambda target, credentials, settings: SqlServerTestResult(
            False, "Connection failed; check server and credentials"
        ),
    )
    response = client.post("/api/databases/test", json={"connection": _connection_payload()})
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "Never-return-this-password" not in response.text


def test_database_access_grants_filter_standard_user_connections(client, test_session_factory):
    _admin_login(client)
    created = _create_connection(client)
    connection_id = created["id"]
    with test_session_factory() as db:
        viewer = User(
            email="viewer@example.com",
            full_name="Report Viewer",
            password_hash=hash_password("viewer password for test"),
            role=UserRole.VIEWER.value,
        )
        db.add(viewer)
        db.commit()
        viewer_id = viewer.id

    with TestClient(app) as viewer_client:
        login = viewer_client.post(
            "/api/auth/login",
            json={"email": "viewer@example.com", "password": "viewer password for test"},
        )
        assert login.status_code == 200
        assert viewer_client.get("/api/databases").json()["items"] == []

        granted = client.put(
            f"/api/databases/{connection_id}/access/{viewer_id}", json={"permission": "read"}
        )
        assert granted.status_code == 200
        assert granted.json()["permission"] == "read"
        assert viewer_client.get("/api/databases").json()["items"][0]["id"] == connection_id

        revoked = client.delete(f"/api/databases/{connection_id}/access/{viewer_id}")
        assert revoked.status_code == 204
        assert viewer_client.get("/api/databases").json()["items"] == []


def test_database_access_management_and_delete_are_role_protected(client):
    _admin_login(client)
    created = _create_connection(client)
    response = client.get(f"/api/databases/{created['id']}/access")
    assert response.status_code == 200
    assert response.json() == {"items": []}
    deleted = client.delete(f"/api/databases/{created['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/databases").json()["items"] == []


def test_standard_user_cannot_create_database(client, test_session_factory):
    with test_session_factory() as db:
        viewer = User(
            email="limited@example.com",
            full_name="Limited User",
            password_hash=hash_password("limited password for test"),
            role=UserRole.VIEWER.value,
        )
        db.add(viewer)
        db.commit()
    with TestClient(app) as viewer_client:
        viewer_client.post(
            "/api/auth/login",
            json={"email": "limited@example.com", "password": "limited password for test"},
        )
        response = viewer_client.post("/api/databases", json=_connection_payload())
    assert response.status_code == 403
