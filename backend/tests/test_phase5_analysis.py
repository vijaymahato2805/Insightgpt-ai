from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api.comparisons as comparisons_api
import app.api.conversations as conversations_api
import app.api.insights as insights_api
from app.core.security import hash_password
from app.main import app
from app.models.erp import (
    CompanyMapping,
    SchemaColumn,
    SchemaObject,
    UserDatabaseAccess,
)
from app.models.user import User, UserRole
from app.schemas.analysis import InsightEvidence, InsightPlan, InsightRequest, InsightResponse
from app.services.comparisons import (
    ComparisonInputError,
    aggregate_rows,
    apply_conversation_filters,
    apply_date_range,
    canonicalize_company_result,
    convert_currency,
)
from app.services.insights import BusinessInsightService
from app.services.text_to_sql import load_query_context
from tests.test_text_to_sql import _seed_nav_schema


def _context_for(client, factory, connection_data, mapping_id=None):
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        return load_query_context(db, user, UUID(connection_data["id"]), mapping_id)


def test_conversation_filter_ast_is_safe_and_date_ranges_are_schema_bound(client, test_session_factory):
    connection = _seed_nav_schema(client, test_session_factory)
    with test_session_factory() as db:
        obj = db.scalar(
            select(SchemaObject).where(
                SchemaObject.database_connection_id == UUID(connection["id"]),
                SchemaObject.object_name == "Contoso$Sales Header",
            )
        )
        date_column = db.scalar(
            select(SchemaColumn).where(
                SchemaColumn.schema_object_id == obj.id,
                SchemaColumn.column_name == "Posting Date",
            )
        )
        date_column.data_type = "date"
        db.commit()

    context = _context_for(client, test_session_factory, connection)
    sql = "SELECT h.[Posting Date], h.[Sell-to Customer No_] FROM dbo.[Contoso$Sales Header] h"
    filtered = apply_conversation_filters(
        context,
        sql,
        [{"field": "Sell-to Customer No_", "value": "C'100' OR 1=1 --"}],
    )
    assert "h.[Sell-to Customer No_] = 'C''100'' OR 1=1 --'" in filtered

    bounded = apply_date_range(
        context,
        sql,
        "Posting Date",
        date(2026, 1, 1),
        date(2026, 1, 31),
    )
    assert "h.[Posting Date] >= '2026-01-01'" in bounded
    assert "h.[Posting Date] < '2026-02-01'" in bounded
    with pytest.raises(ComparisonInputError, match="one discovered date column"):
        apply_date_range(context, sql, "Unmapped Date", date(2026, 1, 1), date(2026, 1, 31))


def test_schema_filter_rejects_ambiguous_and_non_discovered_columns(client, test_session_factory):
    connection = _seed_nav_schema(client, test_session_factory)
    context = _context_for(client, test_session_factory, connection)
    sql = "SELECT h.[No_] FROM dbo.[Contoso$Sales Header] h JOIN dbo.[Contoso$Sales Line] l ON h.[No_] = l.[Document No_]"
    with pytest.raises(ComparisonInputError, match="one discovered query column"):
        apply_conversation_filters(context, sql, [{"field": "No_", "value": "100"}])
    with pytest.raises(ComparisonInputError, match="one discovered query column"):
        apply_conversation_filters(context, sql, [{"field": "not a real column", "value": "x"}])


def test_company_field_normalization_and_currency_conversion():
    alpha = SimpleNamespace(
        field_mappings={"sales": {"sales_amount": "Amount LCY", "category": "Item Group"}}
    )
    beta = SimpleNamespace(
        field_mappings={"sales": {"sales_amount": "Sales Value", "category": "Item Category"}}
    )
    alpha_columns, alpha_rows = canonicalize_company_result(
        alpha, ["Amount LCY", "Item Group"], [{"Amount LCY": "100", "Item Group": "Parts"}]
    )
    beta_columns, beta_rows = canonicalize_company_result(
        beta,
        ["Sales Value", "Item Category"],
        [{"Sales Value": "100", "Item Category": "Parts"}],
    )
    assert alpha_columns == beta_columns == ["sales_amount", "category"]
    assert alpha_rows[0]["category"] == beta_rows[0]["category"]
    converted = convert_currency(
        beta_rows,
        ["sales_amount"],
        "EUR",
        "USD",
        {"EUR": Decimal("1.1")},
    )
    assert converted[0]["sales_amount"] == "110"
    assert aggregate_rows(converted, "sales_amount", ["category"]) == {
        ("Parts",): Decimal(110)
    }
    with pytest.raises(ComparisonInputError, match="exchange rate"):
        convert_currency(beta_rows, ["sales_amount"], "EUR", "USD", {})


@pytest.mark.asyncio
async def test_insight_evidence_is_resolved_from_real_result_rows(test_settings, monkeypatch):
    plan = InsightPlan.model_validate(
        {
            "summary": "Sales are higher in the parts group.",
            "insights": [
                {
                    "title": "Parts lead",
                    "observation": "Parts account for the largest amount in this result.",
                    "direction": "up",
                    "evidence": [{"row_index": 0, "field": "Category"}],
                }
            ],
        }
    )

    class FakeSQLService:
        def __init__(self, settings):
            pass

        async def _structured_call(self, *args, **kwargs):
            return plan

    monkeypatch.setattr("app.services.insights.TextToSQLService", FakeSQLService)
    result = await BusinessInsightService(test_settings).analyze(
        database_id=uuid4(),
        company_mapping_id=None,
        company_name="Contoso",
        request=InsightRequest(database_id=uuid4(), question="What changed?"),
        sql="SELECT Category, Amount FROM dbo.Sales",
        columns=["Category", "Amount"],
        rows=[{"Category": "Parts", "Amount": "125.00"}],
        row_count=1,
        truncated=False,
    )
    assert result.insights[0].evidence[0].value == "Parts"

    plan.insights[0].evidence[0].field = "Password"
    with pytest.raises(ValueError, match="outside the executed result"):
        await BusinessInsightService(test_settings).analyze(
            database_id=uuid4(), company_mapping_id=None, company_name=None,
            request=InsightRequest(database_id=uuid4(), question="What changed?"),
            sql="SELECT Category FROM dbo.Sales", columns=["Category"],
            rows=[{"Category": "Parts"}], row_count=1, truncated=False,
        )


class FakeGeneratedService:
    def __init__(self, settings):
        pass

    async def generate(self, context, question):
        sql = "SELECT h.[No_] FROM dbo.[Contoso$Sales Header] h"
        result = SimpleNamespace(
            sql=sql, needs_clarification=False, clarification=None,
            explanation="Returned posted sales header identifiers.", question=question,
        )
        return result, None, None


def test_conversation_followup_keeps_database_company_filters_and_result_context(
    client, test_session_factory, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    mapping_response = client.post(
        "/api/company-mappings",
        json={
            "database_connection_id": connection["id"],
            "company_name": "Contoso",
            "field_mappings": {"sales_header": {"customer_no": "Sell-to Customer No_"}},
            "table_mappings": {},
            "currency_code": "usd",
        },
    )
    assert mapping_response.status_code == 201, mapping_response.text
    mapping = mapping_response.json()
    assert mapping["currency_code"] == "USD"
    executed = []
    model_questions = []

    class CapturingGeneratedService(FakeGeneratedService):
        async def generate(self, context, question):
            model_questions.append(question)
            return await super().generate(context, question)

    monkeypatch.setattr(conversations_api, "TextToSQLService", CapturingGeneratedService)

    def fake_execute(context, validation, settings):
        executed.append((context.company_label, validation.sql))
        return ["No_"], [{"No_": f"SO-{len(executed)}"}], False

    monkeypatch.setattr(conversations_api, "execute_validated_sql", fake_execute)
    first = client.post(
        "/api/conversations/ask",
        json={
            "database_id": connection["id"],
            "company_mapping_id": mapping["id"],
            "question": "Show orders for customer C100",
            "active_filters": [{"field": "Sell-to Customer No_", "value": "C'100"}],
        },
    )
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["active_filters"] == [{"field": "Sell-to Customer No_", "value": "C'100"}]
    assert first_data["company_mapping_id"] == mapping["id"]
    assert "h.[Sell-to Customer No_] = 'C''100'" in executed[0][1]

    followup = client.post(
        "/api/conversations/ask",
        json={"conversation_id": first_data["id"], "question": "Break that down by month"},
    )
    assert followup.status_code == 200, followup.text
    assert followup.json()["database_connection_id"] == connection["id"]
    assert followup.json()["company_mapping_id"] == mapping["id"]
    assert followup.json()["active_filters"] == first_data["active_filters"]
    assert "h.[Sell-to Customer No_] = 'C''100'" in executed[1][1]
    assert len(followup.json()["messages"]) == 4
    assert "Show orders for customer C100" in model_questions[1]
    assert "SO-1" in model_questions[1]
    assert "C'100" in model_questions[1]
    assert "Never-return-this-password" not in followup.text

    wrong_scope = client.post(
        "/api/conversations/ask",
        json={
            "conversation_id": first_data["id"],
            "database_id": str(uuid4()),
            "question": "Change database",
        },
    )
    assert wrong_scope.status_code == 409
    wrong_company = client.post(
        "/api/conversations/ask",
        json={
            "conversation_id": first_data["id"],
            "company_mapping_id": str(uuid4()),
            "question": "Change company",
        },
    )
    assert wrong_company.status_code == 409
    assert client.get(f"/api/conversations/{first_data['id']}").status_code == 200
    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == first_data["id"]
    assert client.delete(f"/api/conversations/{first_data['id']}").status_code == 204


def test_conversation_endpoints_recheck_database_access_on_every_request(
    client, test_session_factory, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    with test_session_factory() as db:
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        viewer = User(
            email="phase5-viewer@example.com", full_name="Viewer",
            password_hash=hash_password("phase5 viewer password"), role=UserRole.VIEWER.value,
        )
        db.add(viewer)
        db.flush()
        db.add(UserDatabaseAccess(
            user_id=viewer.id, database_connection_id=UUID(connection["id"]),
            permission="read", granted_by=admin.id,
        ))
        db.commit()
        viewer_id = viewer.id
    monkeypatch.setattr(conversations_api, "TextToSQLService", FakeGeneratedService)
    monkeypatch.setattr(
        conversations_api, "execute_validated_sql",
        lambda context, validation, settings: (["No_"], [{"No_": "100"}], False),
    )
    with TestClient(app) as viewer_client:
        login = viewer_client.post(
            "/api/auth/login",
            json={"email": "phase5-viewer@example.com", "password": "phase5 viewer password"},
        )
        assert login.status_code == 200
        created = viewer_client.post(
            "/api/conversations/ask",
            json={"database_id": connection["id"], "question": "Show order ids"},
        )
        assert created.status_code == 200, created.text
        conversation_id = created.json()["id"]
        with test_session_factory() as db:
            db.query(UserDatabaseAccess).filter_by(
                user_id=viewer_id, database_connection_id=UUID(connection["id"])
            ).delete()
            db.commit()
        denied_get = viewer_client.get(f"/api/conversations/{conversation_id}")
        denied_followup = viewer_client.post(
            "/api/conversations/ask",
            json={"conversation_id": conversation_id, "question": "And by month?"},
        )
    assert denied_get.status_code == 404
    assert denied_followup.status_code == 404


def test_business_insight_api_uses_validated_execution_and_returns_result_evidence(
    client, test_session_factory, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    monkeypatch.setattr(insights_api, "TextToSQLService", FakeGeneratedService)
    monkeypatch.setattr(
        insights_api,
        "execute_validated_sql",
        lambda context, validation, settings: (
            ["No_"], [{"No_": "SO-100"}], False
        ),
    )

    class FakeInsightPlanner:
        def __init__(self, settings):
            pass

        async def analyze(self, **kwargs):
            return InsightResponse(
                database_id=kwargs["database_id"],
                company_mapping_id=kwargs["company_mapping_id"],
                company_name=kwargs["company_name"],
                question=kwargs["request"].question,
                sql=kwargs["sql"],
                columns=kwargs["columns"],
                row_count=kwargs["row_count"],
                truncated=kwargs["truncated"],
                summary="One order is in the result.",
                insights=[{
                    "title": "Order returned",
                    "observation": "The query returned order SO-100.",
                    "direction": "notable",
                    "evidence": [InsightEvidence(field="No_", value=kwargs["rows"][0]["No_"])],
                }],
            )

    monkeypatch.setattr(insights_api, "BusinessInsightService", FakeInsightPlanner)
    response = client.post(
        "/api/insights/generate",
        json={"database_id": connection["id"], "question": "Summarize posted orders"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["insights"][0]["evidence"] == [{"field": "No_", "value": "SO-100"}]
    assert "Never-return-this-password" not in response.text


def _seed_comparison_mappings(client, factory, connection):
    with factory() as db:
        alpha = CompanyMapping(
            database_connection_id=UUID(connection["id"]), company_name="Alpha", erp_version="nav_2018",
            table_mappings={}, field_mappings={"sales": {"sales_amount": "Amount LCY", "category": "Item Group"}}, currency_code="USD",
        )
        beta = CompanyMapping(
            database_connection_id=UUID(connection["id"]), company_name="Beta", erp_version="nav_2018",
            table_mappings={}, field_mappings={"sales": {"sales_amount": "Sales Value", "category": "Item Category"}}, currency_code="EUR",
        )
        db.add_all([alpha, beta])
        db.flush()
        for company, metric, dimension in [
            ("Alpha", "Amount LCY", "Item Group"),
            ("Beta", "Sales Value", "Item Category"),
        ]:
            obj = SchemaObject(
                database_connection_id=UUID(connection["id"]), schema_name="dbo",
                object_name=f"{company}$Sales Entry", object_type="table",
            )
            db.add(obj)
            db.flush()
            db.add_all([
                SchemaColumn(schema_object_id=obj.id, column_name=metric, ordinal_position=1,
                             data_type="decimal(18,2)", nullable=False, is_primary_key=False, is_foreign_key=False),
                SchemaColumn(schema_object_id=obj.id, column_name=dimension, ordinal_position=2,
                             data_type="nvarchar(100)", nullable=False, is_primary_key=False, is_foreign_key=False),
            ])
        db.commit()
        ids = {item.company_name: str(item.id) for item in db.scalars(select(CompanyMapping))
               if item.company_name in {"Alpha", "Beta"}}
        return ids


class FakeCompanyQueryService:
    def __init__(self, settings):
        pass

    async def generate(self, context, question):
        name = context.company_mapping.company_name
        actual_metric = "Amount LCY" if name == "Alpha" else "Sales Value"
        actual_dimension = "Item Group" if name == "Alpha" else "Item Category"
        table = f"{name}$Sales Entry"
        result = SimpleNamespace(
            sql=f"SELECT s.[{actual_metric}], s.[{actual_dimension}] FROM dbo.[{table}] s",
            needs_clarification=False, clarification=None,
        )
        return result, None, None


def test_company_comparison_normalizes_nav_fields_and_currency_per_series(
    client, test_session_factory, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    mapping_ids = _seed_comparison_mappings(client, test_session_factory, connection)
    monkeypatch.setattr(comparisons_api, "TextToSQLService", FakeCompanyQueryService)

    def fake_execute(context, validation, settings):
        if context.company_mapping.company_name == "Alpha":
            return ["Amount LCY", "Item Group"], [{"Amount LCY": "100", "Item Group": "Parts"}], False
        return ["Sales Value", "Item Category"], [{"Sales Value": "100", "Item Category": "Parts"}], False

    monkeypatch.setattr(comparisons_api, "execute_validated_sql", fake_execute)
    response = client.post(
        "/api/comparisons/companies",
        json={
            "database_id": connection["id"], "company_mapping_ids": [mapping_ids["Alpha"], mapping_ids["Beta"]],
            "question": "Compare posted sales value", "metric_field": "sales_amount",
            "dimension_fields": ["category"], "currency_fields": ["sales_amount"],
            "target_currency_code": "USD", "exchange_rates": {"EUR": "1.1"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"][0]["values_by_company"] == {"Alpha": "100", "Beta": "110"}
    assert payload["rows"][0]["changes_vs_baseline"]["Beta"]["absolute_change"] == "10"
    assert payload["companies"][1]["columns"] == ["sales_amount", "category"]
    assert payload["companies"][1]["rows"][0]["sales_amount"] == "110"


def test_company_comparison_rejects_company_scope_escape(client, test_session_factory, monkeypatch):
    connection = _seed_nav_schema(client, test_session_factory)
    mapping_ids = _seed_comparison_mappings(client, test_session_factory, connection)

    class EscapingService:
        def __init__(self, settings):
            pass

        async def generate(self, context, question):
            result = SimpleNamespace(
                sql="SELECT b.[Sales Value] FROM dbo.[Beta$Sales Entry] b",
                needs_clarification=False, clarification=None,
            )
            return result, None, None

    monkeypatch.setattr(comparisons_api, "TextToSQLService", EscapingService)
    denied = client.post(
        "/api/comparisons/companies",
        json={
            "database_id": connection["id"], "company_mapping_ids": [mapping_ids["Alpha"], mapping_ids["Beta"]],
            "question": "Compare sales", "metric_field": "sales_amount",
        },
    )
    assert denied.status_code == 422
    assert "Beta$Sales Entry" in denied.text


def test_period_comparison_adds_exact_dates_and_returns_change(client, test_session_factory, monkeypatch):
    connection = _seed_nav_schema(client, test_session_factory)
    with test_session_factory() as db:
        header = db.scalar(select(SchemaObject).where(
            SchemaObject.database_connection_id == UUID(connection["id"]),
            SchemaObject.object_name == "Contoso$Sales Header",
        ))
        date_column = db.scalar(select(SchemaColumn).where(
            SchemaColumn.schema_object_id == header.id, SchemaColumn.column_name == "Posting Date",
        ))
        date_column.data_type = "date"
        db.add(SchemaColumn(
            schema_object_id=header.id, column_name="Sales Amount", ordinal_position=4,
            data_type="decimal(18,2)", nullable=False, is_primary_key=False, is_foreign_key=False,
        ))
        db.commit()

    class PeriodQueryService:
        def __init__(self, settings):
            pass

        async def generate(self, context, question):
            return SimpleNamespace(
                sql="SELECT h.[Posting Date], SUM(h.[Sales Amount]) AS [Sales Amount] FROM dbo.[Contoso$Sales Header] h GROUP BY h.[Posting Date]",
                needs_clarification=False, clarification=None,
            ), None, None

    monkeypatch.setattr(comparisons_api, "TextToSQLService", PeriodQueryService)
    executed_sql = []

    def fake_execute(context, validation, settings):
        executed_sql.append(validation.sql)
        value = "120" if ">= '2026-01-01'" in validation.sql else "100"
        return ["Posting Date", "Sales Amount"], [{"Posting Date": "period", "Sales Amount": value}], False

    monkeypatch.setattr(comparisons_api, "execute_validated_sql", fake_execute)
    response = client.post(
        "/api/comparisons/periods",
        json={
            "database_id": connection["id"], "question": "Compare posted sales amount",
            "date_field": "Posting Date", "metric_field": "Sales Amount", "dimension_fields": [],
            "current_start": "2026-01-01", "current_end": "2026-01-31",
            "comparison_start": "2025-12-01", "comparison_end": "2025-12-31",
        },
    )
    assert response.status_code == 200, response.text
    assert len(executed_sql) == 2
    assert "h.[Posting Date] >= '2026-01-01'" in executed_sql[0]
    assert "h.[Posting Date] < '2026-02-01'" in executed_sql[0]
    assert response.json()["rows"][0]["absolute_change"] == "20"
    assert response.json()["rows"][0]["percentage_change"] == "20"


def test_comparison_request_rejects_overlapping_periods():
    from app.schemas.analysis import PeriodComparisonRequest

    with pytest.raises(ValueError, match="must not overlap"):
        PeriodComparisonRequest(
            database_id=uuid4(), question="Compare sales", date_field="Posting Date",
            metric_field="Sales Amount", current_start="2026-01-01", current_end="2026-01-31",
            comparison_start="2026-01-31", comparison_end="2026-02-28",
        )
