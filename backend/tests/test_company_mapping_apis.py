from tests.test_database_apis import _admin_login, _create_connection


def test_company_mapping_crud_and_identifier_validation(client):
    _admin_login(client)
    connection = _create_connection(client)
    mapping_payload = {
        "database_connection_id": connection["id"],
        "company_name": "Contoso",
        "table_mappings": {"sales_header": "dbo.Contoso$Sales Header"},
        "field_mappings": {"sales_header": {"posting_date": "Posting Date"}},
    }
    created = client.post("/api/company-mappings", json=mapping_payload)
    assert created.status_code == 201, created.text
    mapping = created.json()
    assert mapping["is_auto_generated"] is False
    assert mapping["table_mappings"]["sales_header"] == "dbo.Contoso$Sales Header"

    listing = client.get(f"/api/company-mappings?database_connection_id={connection['id']}")
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1

    updated = client.put(
        f"/api/company-mappings/{mapping['id']}",
        json={
            **mapping_payload,
            "table_mappings": {"sales_header": "dbo.Contoso$Posted Sales Header"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["table_mappings"]["sales_header"] == "dbo.Contoso$Posted Sales Header"

    invalid = client.post(
        "/api/company-mappings",
        json={
            **mapping_payload,
            "company_name": "Unsafe",
            "table_mappings": {"sales_header": "Sales; DROP TABLE users"},
        },
    )
    assert invalid.status_code == 422
    assert client.delete(f"/api/company-mappings/{mapping['id']}").status_code == 204
    assert (
        client.get(f"/api/company-mappings?database_connection_id={connection['id']}").json()[
            "items"
        ]
        == []
    )


def test_duplicate_company_mapping_is_rejected(client):
    _admin_login(client)
    connection = _create_connection(client)
    payload = {"database_connection_id": connection["id"], "company_name": "Contoso"}
    assert client.post("/api/company-mappings", json=payload).status_code == 201
    assert client.post("/api/company-mappings", json=payload).status_code == 409
