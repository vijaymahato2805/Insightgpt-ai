from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import app.api.sql as sql_api
from app.core.security import hash_password
from app.llm.provider import ChatResult
from app.main import app
from app.models.erp import (
    BusinessDictionaryEntry,
    SchemaColumn,
    SchemaObject,
    SchemaRelationship,
)
from app.models.user import User, UserRole
from app.services import text_to_sql
from app.sql.validation import AllowedTable, SQLPolicyError, validate_read_query
from tests.test_database_apis import _admin_login, _create_connection


def _seed_nav_schema(client, test_session_factory):
    _admin_login(client)
    connection_data = _create_connection(client)
    connection_id = UUID(connection_data["id"])
    with test_session_factory() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        header = SchemaObject(
            database_connection_id=connection_id,
            schema_name="dbo",
            object_name="Contoso$Sales Header",
            object_type="table",
            description="Posted sales order header",
        )
        line = SchemaObject(
            database_connection_id=connection_id,
            schema_name="dbo",
            object_name="Contoso$Sales Line",
            object_type="table",
            description="Posted sales order lines",
        )
        item = SchemaObject(
            database_connection_id=connection_id,
            schema_name="dbo",
            object_name="Contoso$Item",
            object_type="table",
            description="Item master",
        )
        db.add_all([header, line, item])
        db.flush()
        for schema_object, columns in [
            (
                header,
                [("No_", 1, True), ("Posting Date", 2, False), ("Sell-to Customer No_", 3, False)],
            ),
            (
                line,
                [
                    ("Document No_", 1, False),
                    ("Line No_", 2, True),
                    ("No_", 3, False),
                    ("Quantity", 4, False),
                ],
            ),
            (item, [("No_", 1, True), ("Description", 2, False), ("Item Category Code", 3, False)]),
        ]:
            for name, ordinal, primary_key in columns:
                db.add(
                    SchemaColumn(
                        schema_object_id=schema_object.id,
                        column_name=name,
                        ordinal_position=ordinal,
                        data_type="nvarchar(128)" if name != "Quantity" else "decimal(38,20)",
                        nullable=not primary_key,
                        is_primary_key=primary_key,
                        is_foreign_key=name in {"Document No_", "No_"} and schema_object is line,
                    )
                )
        db.add_all(
            [
                SchemaRelationship(
                    source_object_id=line.id,
                    source_column="Document No_",
                    target_schema="dbo",
                    target_table=header.object_name,
                    target_column="No_",
                    constraint_name="FK_SalesLine_Header",
                ),
                SchemaRelationship(
                    source_object_id=line.id,
                    source_column="No_",
                    target_schema="dbo",
                    target_table=item.object_name,
                    target_column="No_",
                    constraint_name="FK_SalesLine_Item",
                ),
            ]
        )
        db.add(
            BusinessDictionaryEntry(
                term="Sales Quantity",
                definition="Sum the posted sales line Quantity field; confirm sign and return handling for each company.",
                entry_type="metric",
                database_connection_id=connection_id,
                created_by=admin.id,
            )
        )
        db.commit()
    return connection_data


def test_sqlglot_accepts_complex_nav_joins_and_sql_server_date_calculations():
    allowed = [
        AllowedTable(
            "dbo",
            "Contoso$Sales Header",
            frozenset({"no_", "posting date", "sell-to customer no_"}),
        ),
        AllowedTable(
            "dbo",
            "Contoso$Sales Line",
            frozenset({"document no_", "line no_", "no_", "quantity"}),
        ),
        AllowedTable(
            "dbo",
            "Contoso$Item",
            frozenset({"no_", "description", "item category code"}),
        ),
    ]
    query = """
        SELECT i.[Item Category Code], SUM(l.Quantity) AS TotalQuantity
        FROM dbo.[Contoso$Sales Header] AS h
        INNER JOIN dbo.[Contoso$Sales Line] AS l ON h.[No_] = l.[Document No_]
        INNER JOIN dbo.[Contoso$Item] AS i ON l.[No_] = i.[No_]
        WHERE h.[Posting Date] >= DATEADD(month, DATEDIFF(month, 0, GETDATE()), 0)
        GROUP BY i.[Item Category Code]
        ORDER BY TotalQuantity DESC
    """
    result = validate_read_query(query, allowed, max_rows=250)
    assert "TOP 250" in result.sql
    assert result.tables == [
        "dbo.Contoso$Item",
        "dbo.Contoso$Sales Header",
        "dbo.Contoso$Sales Line",
    ]
    assert "dbo.Contoso$Sales Header.Posting Date" in result.columns
    assert "dbo.Contoso$Sales Line.Quantity" in result.columns


def test_sqlglot_rejects_invalid_columns_unapproved_tables_and_unsafe_statements():
    allowed = [AllowedTable("dbo", "Contoso$Item", frozenset({"no_", "description"}))]
    with pytest.raises(SQLPolicyError, match="Missing Field"):
        validate_read_query(
            "SELECT i.[Missing Field] FROM dbo.[Contoso$Item] i", allowed, max_rows=100
        )
    with pytest.raises(SQLPolicyError, match="Missing Field"):
        validate_read_query("SELECT [Missing Field] FROM dbo.[Contoso$Item]", allowed, max_rows=100)
    with pytest.raises(SQLPolicyError, match="not available"):
        validate_read_query("SELECT * FROM dbo.SecretTable", allowed, max_rows=100)
    with pytest.raises(SQLPolicyError, match="Cross-database"):
        validate_read_query("SELECT * FROM OtherCompany.dbo.[Contoso$Item]", allowed, max_rows=100)
    with pytest.raises(SQLPolicyError, match="read-only SELECT"):
        validate_read_query("DELETE FROM dbo.[Contoso$Item]", allowed, max_rows=100)
    with pytest.raises(SQLPolicyError, match="one SQL statement"):
        validate_read_query(
            "SELECT * FROM dbo.[Contoso$Item]; DROP TABLE dbo.X", allowed, max_rows=100
        )
    with pytest.raises(SQLPolicyError, match="query hints and options"):
        validate_read_query(
            "SELECT * FROM dbo.[Contoso$Item] OPTION (MAXDOP 64)", allowed, max_rows=100
        )
    with pytest.raises(SQLPolicyError, match="authorized discovered table"):
        validate_read_query("SELECT 1", allowed, max_rows=100)


def test_sql_validate_api_enforces_schema_columns_and_database_scope(client, test_session_factory):
    connection = _seed_nav_schema(client, test_session_factory)
    response = client.post(
        "/api/sql/validate",
        json={
            "database_id": connection["id"],
            "sql": "SELECT h.[No_] FROM dbo.[Contoso$Sales Header] h",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["max_rows"] == 500

    bad_column = client.post(
        "/api/sql/validate",
        json={
            "database_id": connection["id"],
            "sql": "SELECT h.[Made Up Column] FROM dbo.[Contoso$Sales Header] h",
        },
    )
    assert bad_column.status_code == 422
    assert "Made Up Column" in bad_column.text

    bad_table = client.post(
        "/api/sql/validate",
        json={"database_id": connection["id"], "sql": "SELECT * FROM dbo.SecretTable"},
    )
    assert bad_table.status_code == 422
    assert "not available" in bad_table.text


def test_company_schema_scope_rejects_another_nav_company(client, test_session_factory):
    connection = _seed_nav_schema(client, test_session_factory)
    with test_session_factory() as db:
        other = SchemaObject(
            database_connection_id=UUID(connection["id"]),
            schema_name="dbo",
            object_name="OtherCo$Item",
            object_type="table",
        )
        db.add(other)
        db.flush()
        db.add(
            SchemaColumn(
                schema_object_id=other.id,
                column_name="No_",
                ordinal_position=1,
                data_type="nvarchar(20)",
                nullable=False,
                is_primary_key=True,
                is_foreign_key=False,
            )
        )
        db.commit()
    response = client.post(
        "/api/sql/validate",
        json={
            "database_id": connection["id"],
            "sql": "SELECT i.[No_] FROM dbo.[OtherCo$Item] i",
        },
    )
    assert response.status_code == 422
    assert "OtherCo$Item" in response.text


def test_sql_api_requires_database_permission(client, test_session_factory):
    connection = _seed_nav_schema(client, test_session_factory)
    with test_session_factory() as db:
        viewer = User(
            email="sql-viewer@example.com",
            full_name="SQL Viewer",
            password_hash=hash_password("viewer test password"),
            role=UserRole.VIEWER.value,
        )
        db.add(viewer)
        db.commit()

    with TestClient(app) as viewer_client:
        assert (
            viewer_client.post(
                "/api/auth/login",
                json={"email": "sql-viewer@example.com", "password": "viewer test password"},
            ).status_code
            == 200
        )
        denied = viewer_client.post(
            "/api/sql/validate",
            json={
                "database_id": connection["id"],
                "sql": "SELECT * FROM dbo.[Contoso$Item]",
            },
        )
    assert denied.status_code == 404


def test_sql_execution_api_revalidates_and_returns_bounded_rows(
    client, test_session_factory, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    monkeypatch.setattr(
        sql_api,
        "execute_validated_sql",
        lambda context, validation, settings: (
            ["No_"],
            [{"No_": "1000"}],
            False,
        ),
    )
    response = client.post(
        "/api/sql/execute",
        json={
            "database_id": connection["id"],
            "sql": "SELECT i.[No_] FROM dbo.[Contoso$Item] i",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == [{"No_": "1000"}]
    assert "Never-return-this-password" not in response.text


def test_text_to_sql_runs_intent_selection_correction_and_explanation(
    client, test_session_factory, test_settings, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    object_ids = {}
    with test_session_factory() as db:
        for item in db.query(SchemaObject).filter_by(database_connection_id=UUID(connection["id"])):
            object_ids[item.object_name] = str(item.id)

    class FakeProvider:
        def __init__(self, settings):
            self.prompts = []
            self.generation_count = 0

        async def chat_completion(self, messages, task="fast", temperature=0.2, max_tokens=1200):
            prompt = messages[-1]["content"]
            self.prompts.append(prompt)
            if prompt.startswith("Detect the analytics intent"):
                content = '{"intent":"aggregation","metrics":["quantity"],"dimensions":["month"],"filters":["MTD"],"time_period":"month to date","requested_company":null,"needs_clarification":false,"clarification":null}'
            elif prompt.startswith("Select the smallest set"):
                content = (
                    '{"object_ids":['
                    f'"{object_ids["Contoso$Sales Header"]}",'
                    f'"{object_ids["Contoso$Sales Line"]}"'
                    '],"reason":"The header supplies date and the line supplies quantity."}'
                )
            elif prompt.startswith("Generate exactly one"):
                self.generation_count += 1
                content = (
                    '{"sql":"SELECT h.[Missing Column] FROM dbo.[Contoso$Sales Header] h",'
                    '"assumptions":[]}'
                )
            elif prompt.startswith("Correct the SQL Server"):
                content = (
                    '{"sql":"SELECT h.[Posting Date], SUM(l.Quantity) AS TotalQuantity '
                    "FROM dbo.[Contoso$Sales Header] h JOIN dbo.[Contoso$Sales Line] l "
                    "ON h.[No_] = l.[Document No_] "
                    "WHERE h.[Posting Date] >= DATEADD(month, DATEDIFF(month, 0, GETDATE()), 0) "
                    'GROUP BY h.[Posting Date]","assumptions":[]}'
                )
            elif prompt.startswith("Explain what this validated"):
                content = '{"explanation":"Joins sales headers to lines, filters from the current month, and totals quantity by posting date.","notes":[]}'
            else:
                raise AssertionError(f"Unexpected prompt: {prompt[:80]}")
            return ChatResult(content, "mock/model", 3, 2, 5)

    fake_provider = FakeProvider(test_settings)
    monkeypatch.setattr(text_to_sql, "OpenRouterProvider", lambda settings: fake_provider)
    response = client.post(
        "/api/sql/generate",
        json={"database_id": connection["id"], "question": "Show ILE quantity by month for MTD"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "Missing Column" not in payload["sql"]
    assert "TOP 500" in payload["sql"]
    assert payload["intent"]["intent"] == "aggregation"
    assert "ILE" in payload["business_terms"]
    assert payload["token_usage"]["total_tokens"] == 25
    assert fake_provider.generation_count == 1
    assert any(prompt.startswith("Correct the SQL Server") for prompt in fake_provider.prompts)
    assert "Never-return-this-password" not in "\n".join(fake_provider.prompts)


def test_sql_explain_api_validates_before_calling_the_model(
    client, test_session_factory, test_settings, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)

    class FakeProvider:
        def __init__(self, settings):
            pass

        async def chat_completion(self, messages, task="fast", temperature=0.2, max_tokens=1200):
            assert "Explain what this validated SQL Server SELECT" in messages[-1]["content"]
            return ChatResult(
                '{"explanation":"Reads item identifiers from the selected company.","notes":[]}',
                "mock/model",
                3,
                2,
                5,
            )

    monkeypatch.setattr(text_to_sql, "OpenRouterProvider", FakeProvider)
    response = client.post(
        "/api/sql/explain",
        json={
            "database_id": connection["id"],
            "sql": "SELECT i.[No_] FROM dbo.[Contoso$Item] i",
            "question": "Show item numbers",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["explanation"].startswith("Reads item identifiers")
    assert response.json()["token_usage"]["total_tokens"] == 5


def test_chat_ask_generates_revalidates_and_executes(
    client, test_session_factory, test_settings, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)

    class FakeProvider:
        def __init__(self, settings):
            pass

        async def chat_completion(self, messages, task="fast", temperature=0.2, max_tokens=1200):
            prompt = messages[-1]["content"]
            if prompt.startswith("Detect the analytics intent"):
                content = '{"intent":"lookup","metrics":[],"dimensions":["order number"],"filters":[],"time_period":null,"requested_company":null,"needs_clarification":false,"clarification":null}'
            elif prompt.startswith("Select the smallest set"):
                import json

                candidates = json.loads(prompt.split("Candidate schema objects: ", 1)[1])
                ids = [
                    item["id"]
                    for item in candidates
                    if item["object_name"] == "Contoso$Sales Header"
                ]
                content = json.dumps(
                    {"object_ids": ids, "reason": "Order numbers are in the header."}
                )
            elif prompt.startswith("Generate exactly one"):
                content = (
                    '{"sql":"SELECT h.[No_] FROM dbo.[Contoso$Sales Header] h","assumptions":[]}'
                )
            elif prompt.startswith("Explain what this validated"):
                content = '{"explanation":"Returns sales order numbers.","notes":[]}'
            else:
                raise AssertionError(f"Unexpected prompt: {prompt[:80]}")
            return ChatResult(content, "mock/model", 2, 2, 4)

    monkeypatch.setattr(text_to_sql, "OpenRouterProvider", FakeProvider)
    monkeypatch.setattr(
        sql_api,
        "execute_validated_sql",
        lambda context, validation, settings: (["No_"], [{"No_": "SO-001"}], False),
    )
    response = client.post(
        "/api/chat/ask",
        json={"database_id": connection["id"], "question": "Show posted order numbers"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sql"].startswith("SELECT TOP 500")
    assert response.json()["rows"] == [{"No_": "SO-001"}]
    assert response.json()["row_count"] == 1
