def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_system_status_reports_database_and_never_exposes_provider_secret(client):
    response = client.get("/api/system/status")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "connected"
    assert "openrouter_api_key" not in body
