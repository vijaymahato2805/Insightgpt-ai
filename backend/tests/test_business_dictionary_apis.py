from tests.test_database_apis import _admin_login, _create_connection


def test_business_dictionary_crud_and_scoped_validation(client):
    _admin_login(client)
    connection = _create_connection(client)
    dictionary = {
        "term": "ILE",
        "definition": "Item Ledger Entry",
        "entry_type": "term",
        "database_connection_id": connection["id"],
        "enabled": True,
    }
    created = client.post("/api/business-dictionary", json=dictionary)
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["term"] == "ILE"

    listing = client.get(f"/api/business-dictionary?database_connection_id={connection['id']}")
    assert listing.status_code == 200
    assert [item["term"] for item in listing.json()["items"]] == ["ILE"]

    updated = client.put(
        f"/api/business-dictionary/{entry['id']}",
        json={
            **dictionary,
            "term": "Item Ledger Entry",
            "definition": "NAV inventory ledger movements",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["definition"] == "NAV inventory ledger movements"

    duplicate = client.post(
        "/api/business-dictionary", json={**dictionary, "term": "item ledger ENTRY"}
    )
    assert duplicate.status_code == 409
    deleted = client.delete(f"/api/business-dictionary/{entry['id']}")
    assert deleted.status_code == 204
    assert (
        client.get(f"/api/business-dictionary?database_connection_id={connection['id']}").json()[
            "items"
        ]
        == []
    )


def test_business_dictionary_can_be_scoped_to_an_auto_company_mapping(client, monkeypatch):
    import app.api.schema as schema_api
    from tests.test_schema_apis import _snapshot

    _admin_login(client)
    connection = _create_connection(client)
    monkeypatch.setattr(
        schema_api, "discover_sqlserver_schema", lambda *args, **kwargs: _snapshot()
    )
    assert (
        client.post("/api/schema/refresh", json={"database_id": connection["id"]}).status_code
        == 200
    )
    mapping = client.get(f"/api/company-mappings?database_connection_id={connection['id']}").json()[
        "items"
    ][0]

    created = client.post(
        "/api/business-dictionary",
        json={
            "term": "Consumption",
            "definition": "Company-approved consumption quantity rule",
            "entry_type": "rule",
            "company_mapping_id": mapping["id"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["database_connection_id"] == connection["id"]
    scoped = client.get(f"/api/business-dictionary?company_mapping_id={mapping['id']}")
    assert [item["term"] for item in scoped.json()["items"]] == ["Consumption"]


def test_dictionary_routes_require_authentication(client):
    client.post("/api/auth/logout")
    response = client.get("/api/business-dictionary")
    assert response.status_code == 401
