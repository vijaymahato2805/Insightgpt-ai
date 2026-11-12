from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.schemas.dashboard import (
    DashboardFilter,
    DashboardFilterPlan,
    DashboardPlan,
    DashboardResponse,
    DashboardWidget,
    DashboardWidgetPlan,
)
from app.services.text_to_sql import (
    QueryContext,
    TextToSQLService,
    UsageAccumulator,
    _json_dumps,
    _rank_schema,
    _retrieve_business_terms,
    _schema_payload,
)
from app.sql.contracts import QueryIntent, TokenUsage

PROMPT_NAME = "dashboard_generation.txt"


@dataclass(frozen=True)
class ExecutedWidget:
    plan: DashboardWidgetPlan
    sql: str
    explanation: str
    columns: list[str]
    rows: list[dict[str, object]]
    truncated: bool


class DashboardService:
    """Creates a constrained dashboard plan using the existing OpenRouter setup."""

    def __init__(self, settings: Settings):
        self.sql_service = TextToSQLService(settings)

    async def create_plan(
        self, context: QueryContext, question: str
    ) -> tuple[DashboardPlan, TokenUsage]:
        terms = _retrieve_business_terms(context, question)
        intent = QueryIntent(intent="dashboard planning")
        candidates = _rank_schema(context, question, intent, terms)
        schema = [_schema_payload(context, item) for item, _ in candidates[:24]]
        usage = UsageAccumulator()
        plan = await self.sql_service._structured_call(
            DashboardPlan,
            PROMPT_NAME,
            {
                "QUESTION": json.dumps(question, ensure_ascii=False),
                "COMPANY": json.dumps(context.company_label, ensure_ascii=False),
                "SCHEMA": _json_dumps(schema),
                "TERMS": _json_dumps([term.model_dump() for term in terms]),
            },
            task="reasoning",
            usage=usage,
        )
        return plan, usage.to_schema()


def assemble_dashboard(
    *,
    database_id: UUID,
    company_mapping_id: UUID | None,
    question: str,
    plan: DashboardPlan,
    executed_widgets: list[ExecutedWidget],
) -> DashboardResponse:
    widgets = [_assemble_widget(item.plan, item) for item in executed_widgets]
    filters = _assemble_filters(plan.filters, widgets)
    return DashboardResponse(
        database_id=database_id,
        company_mapping_id=company_mapping_id,
        question=question,
        title=plan.title,
        description=plan.description,
        filters=filters,
        widgets=widgets,
    )


def _assemble_widget(plan: DashboardWidgetPlan, execution: ExecutedWidget) -> DashboardWidget:
    columns = execution.columns
    rows = execution.rows
    value_field = _resolve_field(columns, plan.value_field_hint, rows, numeric=True)
    category_field = _resolve_field(
        columns,
        plan.category_field_hint,
        rows,
        numeric=False,
        exclude={value_field} if value_field else set(),
    )
    series_field = _resolve_field(
        columns,
        plan.series_field_hint,
        rows,
        numeric=False,
        exclude={category_field, value_field} - {None},
    )
    drilldown_field = _resolve_field(
        columns,
        plan.drilldown_field_hint,
        rows,
        numeric=False,
        exclude={value_field} if value_field else set(),
    )
    if drilldown_field is None:
        drilldown_field = category_field

    return DashboardWidget(
        widget_id=plan.widget_id,
        title=plan.title,
        visualization=plan.visualization,
        question=plan.question,
        layout_span=plan.layout_span,
        sql=execution.sql,
        explanation=execution.explanation,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=execution.truncated,
        category_field=category_field,
        value_field=value_field,
        series_field=series_field,
        drilldown_field=drilldown_field,
    )


def _assemble_filters(
    plans: list[DashboardFilterPlan], widgets: list[DashboardWidget]
) -> list[DashboardFilter]:
    result: list[DashboardFilter] = []
    for plan in plans:
        field = _resolve_field(
            [column for widget in widgets for column in widget.columns],
            plan.field_hint,
            [row for widget in widgets for row in widget.rows],
            numeric=False,
        )
        if field is None:
            continue
        values: list[str] = []
        seen: set[str] = set()
        for widget in widgets:
            if field not in widget.columns:
                continue
            for row in widget.rows:
                value = row.get(field)
                if value is None:
                    continue
                text = str(value)
                if text not in seen:
                    values.append(text)
                    seen.add(text)
                    if len(values) >= 100:
                        break
            if len(values) >= 100:
                break
        result.append(
            DashboardFilter(
                filter_id=plan.filter_id,
                label=plan.label,
                field=field,
                options=values,
            )
        )
    return result


def _resolve_field(
    columns: list[str],
    hint: str | None,
    rows: list[dict[str, object]],
    *,
    numeric: bool,
    exclude: set[str | None] | None = None,
) -> str | None:
    excluded = {item.casefold() for item in (exclude or set()) if item}
    available = [column for column in columns if column.casefold() not in excluded]
    if not available:
        return None
    if hint:
        match = _match_field(available, hint)
        if match:
            return match
    typed = [
        column
        for column in available
        if any(_is_numeric(row.get(column)) for row in rows if row.get(column) is not None)
    ]
    if numeric:
        return (typed or available)[0]
    return next((column for column in available if column not in typed), available[0])


def _match_field(columns: list[str], hint: str) -> str | None:
    folded = hint.casefold().strip()
    exact = [column for column in columns if column.casefold() == folded]
    if exact:
        return exact[0]
    normalized_hint = _normalized(hint)
    if not normalized_hint:
        return None
    normalized = [(column, _normalized(column)) for column in columns]
    exact_normalized = [column for column, value in normalized if value == normalized_hint]
    if exact_normalized:
        return exact_normalized[0]
    partial = [
        column
        for column, value in normalized
        if normalized_hint in value or value in normalized_hint
    ]
    return partial[0] if len(partial) == 1 else None


def _normalized(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _is_numeric(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
            return True
        except ValueError:
            return False
    return False
