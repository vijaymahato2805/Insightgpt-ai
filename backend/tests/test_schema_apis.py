from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, create_engine

import app.api.schema as schema_api
from app.database.schema_discovery import (
    DiscoveredColumn,
    DiscoveredObject,
    DiscoveredRelationship,
    SchemaDiscoveryResult,
    inspect_sqlserver_engine,
)
from tests.test_database_apis import _admin_login, _create_connection


def test_mocked_nav_metadata_discovery_reads_captions_keys_indexes_and_relations(test_settings):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "Object",
        metadata,
        Column("ID", Integer, primary_key=True),
        Column("Name", String(128), nullable=False),
    )
    Table(
        "Field",
        metadata,
        Column("TableNo", Integer, nullable=False),
        Column("FieldName", String(128), nullable=False),
        Column("Caption", String(256), nullable=False),
    )
    header = Table(
        "CRONUS USA, Inc_$Sales Header",
        metadata,
        Column("No_", String(20), primary_key=True),
        Column("Posting Date", String(32)),
    )
    line = Table(
        "CRONUS USA, Inc_$Sales Line",
        metadata,
        Column("Document No_", String(20), ForeignKey(header.c["No_"])),
        Column("Line No_", Integer, primary_key=True),
        Column("Quantity", Integer),
    )
    Index("IX_SalesLine_Quantity", line.c.Quantity)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(metadata.tables["Object"].insert(), [{"ID": 36, "Name": "Sales Header"}])
        connection.execute(
            metadata.tables["Field"].insert(),
            [
                {"TableNo": 36, "FieldName": "No_", "Caption": "Document No."},
                {"TableNo": 36, "FieldName": "Posting Date", "Caption": "Posting Date"},
            ],
        )

    snapshot = inspect_sqlserver_engine(engine, "nav_2018", test_settings)
    header_result = next(
        item for item in snapshot.objects if item.object_name.endswith("Sales Header")
    )
    line_result = next(item for item in snapshot.objects if item.object_name.endswith("Sales Line"))
    assert snapshot.captions_applied == 2
    assert header_result.columns[0].is_primary_key is True
    assert header_result.columns[0].caption == "Document No."
    assert line_result.columns[0].is_foreign_key is True
    assert line_result.relationships[0].target_table.endswith("Sales Header")
    assert any(index["name"] == "IX_SalesLine_Quantity" for index in line_result.indexes)
    engine.dispose()


def _snapshot():
    return SchemaDiscoveryResult(
        objects=[
            DiscoveredObject(
                schema_name="dbo",
                object_name="Contoso$Sales Header",
                object_type="table",
                columns=[
                    DiscoveredColumn(
                        "No_", 1, "nvarchar(20)", False, None, True, False, "Document No."
                    ),
                    DiscoveredColumn(
                        "Posting Date", 2, "datetime", True, None, False, False, "Posting Date"
                    ),
                ],
                indexes=[{"name": "PK_SalesHeader", "columns": ["No_"], "unique": True}],
                relationships=[
                    DiscoveredRelationship(
                        "No_", "dbo", "Contoso$Sales Line", "Document No_", "FK_SalesLine"
                    )
                ],
            ),
            DiscoveredObject(
                schema_name="dbo",
                object_name="Contoso$Sales Line",
                object_type="table",
                columns=[
                    DiscoveredColumn("Document No_", 1, "nvarchar(20)", False, None, False, True),
                    DiscoveredColumn("Quantity", 2, "decimal(38,20)", False, "(0)", False, False),
                ],
            ),
            DiscoveredObject(
                schema_name="dbo",
                object_name="Sales Totals",
                object_type="view",
                columns=[DiscoveredColumn("Total", 1, "decimal(38,20)", True, None, False, False)],
            ),
        ],
        captions_applied=2,
    )


def test_schema_refresh_get_and_description_management_use_mocked_metadata(client, monkeypatch):
    _admin_login(client)
    connection = _create_connection(client)
    monkeypatch.setattr(
        schema_api, "discover_sqlserver_schema", lambda *args, **kwargs: _snapshot()
    )

    refreshed = client.post("/api/schema/refresh", json={"database_id": connection["id"]})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json() == {
        "database_id": connection["id"],
        "objects_discovered": 3,
        "columns_discovered": 5,
        "relationships_discovered": 1,
        "captions_applied": 2,
    }

    schema_response = client.get(f"/api/schema/{connection['id']}?search=Sales%20Header")
    assert schema_response.status_code == 200
    table = schema_response.json()["items"][0]
    assert table["object_name"] == "Contoso$Sales Header"
    assert table["columns"][0]["caption"] == "Document No."
    assert table["relationships"][0]["target_table"] == "Contoso$Sales Line"

    described = client.put(
        f"/api/schema/{connection['id']}/objects/{table['id']}",
        json={"description": "Posted sales document header"},
    )
    assert described.status_code == 200
    assert described.json()["description"] == "Posted sales document header"
    column = table["columns"][1]
    column_result = client.put(
        f"/api/schema/{connection['id']}/columns/{column['id']}",
        json={"description": "Date the document was posted"},
    )
    assert column_result.status_code == 200
    assert column_result.json()["description"] == "Date the document was posted"

    # A refresh replaces physical metadata while preserving administrator descriptions.
    refreshed_again = client.post("/api/schema/refresh", json={"database_id": connection["id"]})
    assert refreshed_again.status_code == 200
    after_refresh = client.get(f"/api/schema/{connection['id']}?search=Sales%20Header").json()
    assert after_refresh["items"][0]["description"] == "Posted sales document header"
    assert after_refresh["items"][0]["columns"][1]["description"] == "Date the document was posted"

    mappings = client.get(f"/api/company-mappings?database_connection_id={connection['id']}")
    assert mappings.status_code == 200
    automatic = next(item for item in mappings.json()["items"] if item["company_name"] == "Contoso")
    assert automatic["is_auto_generated"] is True
    assert automatic["table_mappings"]["sales_header"] == "dbo.Contoso$Sales Header"
    assert automatic["table_mappings"]["sales_line"] == "dbo.Contoso$Sales Line"


def test_schema_refresh_surfaces_safe_driver_error(client, monkeypatch):
    from app.database.sqlserver import SqlServerOperationError

    _admin_login(client)
    connection = _create_connection(client)

    def fail_discovery(*args, **kwargs):
        raise SqlServerOperationError(
            "Schema discovery failed; verify database access and metadata permissions"
        )

    monkeypatch.setattr(schema_api, "discover_sqlserver_schema", fail_discovery)
    response = client.post("/api/schema/refresh", json={"database_id": connection["id"]})
    assert response.status_code == 502
    assert "Never-return-this-password" not in response.text


def test_unauthorized_user_cannot_refresh_or_read_a_database_schema(client):
    response = client.post(
        "/api/schema/refresh", json={"database_id": "00000000-0000-0000-0000-000000000001"}
    )
    assert response.status_code == 401
    read_response = client.get("/api/schema/00000000-0000-0000-0000-000000000001")
    assert read_response.status_code == 401
