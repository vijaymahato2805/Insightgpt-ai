def test_login_and_current_user(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "ADMIN@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert "access_token" in response.cookies
    assert response.cookies.get("access_token")

    current = client.get("/api/auth/me")
    assert current.status_code == 200
    assert current.json()["email"] == "admin@example.com"
    assert "password_hash" not in current.json()


def test_invalid_password_is_rejected(client):
    response = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "wrong"}
    )
    assert response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_the_issued_token(client):
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "correct horse battery staple"},
    )
    old_token = login.cookies["access_token"]
    assert client.post("/api/auth/logout").status_code == 200

    revoked = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert revoked.status_code == 401
