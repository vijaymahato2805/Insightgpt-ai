from uuid import UUID

import pytest
from pydantic import ValidationError

import app.api.dashboards as dashboard_api
from app.llm.provider import ChatResult
from app.models.user import User
from app.schemas.dashboard import DashboardPlan, DashboardWidgetPlan
from app.services import text_to_sql
from app.services.dashboard import DashboardService
from app.services.text_to_sql import LLMOutputError, load_query_context
from app.sql.contracts import QueryIntent, SQLValidationResult, TextToSQLResult, TokenUsage
from tests.test_text_to_sql import _seed_nav_schema


def _plan() -> DashboardPlan:
    return DashboardPlan.model_validate(
        {
            "title": "Sales pulse",
            "description": "A live view of posted sales quantity.",
            "filters": [
                {
                    "filter_id": "posting-period",
                    "label": "Posting period",
                    "field_hint": "PostingMonth",
                }
            ],
            "widgets": [
                {
                    "widget_id": "sales-kpi",
                    "title": "Sales quantity",
                    "visualization": "kpi",
                    "question": "What is total posted sales quantity?",
                    "layout_span": 1,
                    "value_field_hint": "TotalQuantity",
                },
                {
                    "widget_id": "monthly-sales",
                    "title": "Monthly sales quantity",
                    "visualization": "line",
                    "question": "Show posted sales quantity by posting month.",
                    "layout_span": 2,
                    "category_field_hint": "PostingMonth",
                    "value_field_hint": "Quantity",
                    "drilldown_field_hint": "PostingMonth",
                },
                {
                    "widget_id": "sales-detail",
                    "title": "Sales detail",
                    "visualization": "table",
                    "question": "Show posted sales detail by posting month.",
                    "layout_span": 4,
                    "category_field_hint": "PostingMonth",
                    "value_field_hint": "Quantity",
                },
            ],
        }
    )


@pytest.mark.parametrize("visualization", ["kpi", "bar", "line", "area", "pie", "donut", "table"])
def test_dashboard_plan_accepts_each_supported_visualization(visualization):
    widget = DashboardWidgetPlan.model_validate(
        {
            "widget_id": "supported-widget",
            "title": "Supported widget",
            "visualization": visualization,
            "question": "Show quantity by posting date.",
        }
    )
    assert widget.visualization == visualization


def test_dashboard_plan_rejects_unknown_visualizations_duplicate_ids_and_excess_widgets():
    with pytest.raises(ValidationError):
        DashboardWidgetPlan.model_validate(
            {
                "widget_id": "unsafe-widget",
                "title": "Unsafe widget",
                "visualization": "html",
                "question": "Show values.",
            }
        )

    base = _plan().model_dump()
    base["widgets"].append(base["widgets"][0])
    with pytest.raises(ValidationError, match="widget_id values must be unique"):
        DashboardPlan.model_validate(base)


@pytest.mark.asyncio
async def test_dashboard_service_validates_openrouter_json_against_the_plan_contract(
    client, test_session_factory, test_settings, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    with test_session_factory() as db:
        user = db.query(User).filter_by(email="admin@example.com").one()
        context = load_query_context(db, user, UUID(connection["id"]), None)

    class FakeProvider:
        def __init__(self, settings):
            pass

        async def chat_completion(self, messages, task="fast", temperature=0.2, max_tokens=1200):
            prompt = messages[-1]["content"]
            assert prompt.startswith("Create a concise analytical dashboard plan")
            assert "Contoso$Sales Line" in prompt
            assert task == "reasoning"
            return ChatResult(
                '{"title":"Sales","description":"Sales overview","filters":[],"widgets":['
                '{"widget_id":"sales-by-month","title":"Sales by month",'
                '"visualization":"line","question":"Show sales quantity by month",'
                '"layout_span":2,"category_field_hint":"month",'
                '"value_field_hint":"quantity"}]}',
                "mock/model",
                8,
                5,
                13,
            )

    monkeypatch.setattr(text_to_sql, "OpenRouterProvider", FakeProvider)
    plan, usage = await DashboardService(test_settings).create_plan(
        context, "Monthly sales quantity"
    )
    assert plan.widgets[0].visualization == "line"
    assert usage.total_tokens == 13

    class InvalidProvider(FakeProvider):
        async def chat_completion(self, messages, task="fast", temperature=0.2, max_tokens=1200):
            return ChatResult(
                '{"title":"Bad plan","description":"","filters":[],"widgets":['
                '{"widget_id":"unsafe","title":"Unsafe","visualization":"script",'
                '"question":"Show values"}]}',
                "mock/model",
                1,
                1,
                2,
            )

    monkeypatch.setattr(text_to_sql, "OpenRouterProvider", InvalidProvider)
    with pytest.raises(LLMOutputError):
        await DashboardService(test_settings).create_plan(context, "Monthly sales quantity")

    base = _plan().model_dump()
    base["widgets"] = [{**base["widgets"][0], "widget_id": f"widget-{index}"} for index in range(7)]
    with pytest.raises(ValidationError):
        DashboardPlan.model_validate(base)


def test_dashboard_api_executes_each_plan_query_and_returns_database_rows(
    client, test_session_factory, test_settings, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    plan = _plan()
    generated_queries = []
    revalidated_queries = []
    executed_count = 0
    statements = [
        "SELECT SUM(l.[Quantity]) AS [TotalQuantity] FROM dbo.[Contoso$Sales Line] l",
        (
            "SELECT h.[Posting Date] AS [PostingMonth], SUM(l.[Quantity]) AS [Quantity] "
            "FROM dbo.[Contoso$Sales Header] h JOIN dbo.[Contoso$Sales Line] l "
            "ON h.[No_] = l.[Document No_] GROUP BY h.[Posting Date]"
        ),
        (
            "SELECT h.[Posting Date] AS [PostingMonth], SUM(l.[Quantity]) AS [Quantity] "
            "FROM dbo.[Contoso$Sales Header] h JOIN dbo.[Contoso$Sales Line] l "
            "ON h.[No_] = l.[Document No_] GROUP BY h.[Posting Date]"
        ),
    ]

    async def fake_create_plan(self, context, question):
        assert question.startswith("Create a sales dashboard")
        assert "Never-return-this-password" not in question
        return plan, TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    async def fake_generate(self, context, question):
        index = len(generated_queries)
        generated_queries.append(question)
        sql = statements[index]
        result = TextToSQLResult(
            database_id=context.connection.id,
            company_mapping_id=None,
            question=question,
            intent=QueryIntent(intent="aggregation"),
            sql=sql,
            explanation=f"Validated result for {question}",
        )
        validation = SQLValidationResult(
            sql=sql,
            tables=["dbo.Contoso$Sales Line"],
            columns=["Generated value"],
            max_rows=500,
        )
        return result, validation, []

    def fake_execute(context, validation, settings):
        nonlocal executed_count
        revalidated_queries.append(validation.sql)
        current = executed_count
        executed_count += 1
        if current == 0:
            return ["TotalQuantity"], [{"TotalQuantity": "125.50"}], False
        if current == 1:
            return (
                ["PostingMonth", "Quantity"],
                [
                    {"PostingMonth": "2026-01", "Quantity": "44.25"},
                    {"PostingMonth": "2026-02", "Quantity": "81.25"},
                ],
                False,
            )
        return (
            ["PostingMonth", "Quantity"],
            [
                {"PostingMonth": "2026-01", "Quantity": "44.25"},
                {"PostingMonth": "2026-02", "Quantity": "81.25"},
            ],
            False,
        )

    monkeypatch.setattr(DashboardService, "create_plan", fake_create_plan)
    monkeypatch.setattr(dashboard_api.TextToSQLService, "generate", fake_generate)
    monkeypatch.setattr(dashboard_api, "execute_validated_sql", fake_execute)

    response = client.post(
        "/api/dashboards/generate",
        json={
            "database_id": connection["id"],
            "question": "Create a sales dashboard with monthly quantities",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(generated_queries) == len(plan.widgets) == 3
    assert len(revalidated_queries) == 3
    assert payload["title"] == "Sales pulse"
    assert payload["widgets"][0]["rows"] == [{"TotalQuantity": "125.50"}]
    assert payload["widgets"][1]["category_field"] == "PostingMonth"
    assert payload["widgets"][1]["value_field"] == "Quantity"
    assert payload["widgets"][1]["rows"][1]["Quantity"] == "81.25"
    assert payload["filters"] == [
        {
            "filter_id": "posting-period",
            "label": "Posting period",
            "field": "PostingMonth",
            "options": ["2026-01", "2026-02"],
        }
    ]
    assert "sample" not in payload["widgets"][1]["explanation"].casefold()
    assert "Never-return-this-password" not in response.text
