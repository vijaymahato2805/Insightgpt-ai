from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.schemas.dashboard import (
    DashboardPlan,
    DashboardResponse,
    DashboardWidgetPlan,
    SavedDashboardDefinition,
)


def definition_to_snapshot(definition: SavedDashboardDefinition) -> dict[str, Any]:
    plan = DashboardPlan(
        title=definition.title,
        description=definition.description,
        filters=[
            {"filter_id": item.filter_id, "label": item.label, "field_hint": item.field}
            for item in definition.filters
        ],
        widgets=[
            DashboardWidgetPlan(
                widget_id=widget.widget_id,
                title=widget.title,
                visualization=widget.visualization,
                question=widget.question,
                layout_span=widget.layout_span,
                category_field_hint=widget.category_field,
                value_field_hint=widget.value_field,
                series_field_hint=widget.series_field,
                drilldown_field_hint=widget.drilldown_field,
            )
            for widget in definition.widgets
        ],
    )
    return {
        "question": definition.question,
        "plan": plan.model_dump(mode="json"),
        "queries": {
            widget.widget_id: {"sql": widget.sql, "explanation": widget.explanation}
            for widget in definition.widgets
        },
    }


def snapshot_to_plan(snapshot: dict[str, Any]) -> tuple[DashboardPlan, dict[str, dict[str, str]]]:
    plan = DashboardPlan.model_validate(snapshot["plan"])
    queries = snapshot["queries"]
    if set(queries) != {widget.widget_id for widget in plan.widgets}:
        raise ValueError("Saved dashboard query definitions do not match its widgets")
    return plan, queries


def definition_from_response(dashboard: DashboardResponse) -> SavedDashboardDefinition:
    return SavedDashboardDefinition(
        database_id=dashboard.database_id,
        company_mapping_id=dashboard.company_mapping_id,
        question=dashboard.question,
        title=dashboard.title,
        description=dashboard.description,
        filters=[
            {"filter_id": item.filter_id, "label": item.label, "field": item.field}
            for item in dashboard.filters
        ],
        widgets=[
            {
                "widget_id": item.widget_id,
                "title": item.title,
                "visualization": item.visualization,
                "question": item.question,
                "layout_span": item.layout_span,
                "sql": item.sql,
                "explanation": item.explanation,
                "category_field": item.category_field,
                "value_field": item.value_field,
                "series_field": item.series_field,
                "drilldown_field": item.drilldown_field,
            }
            for item in dashboard.widgets
        ],
    )


def apply_selected_filters(
    dashboard: DashboardResponse, selected_filters: dict[str, str]
) -> DashboardResponse:
    by_id = {item.filter_id: item for item in dashboard.filters}
    unknown = set(selected_filters) - set(by_id)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "One or more selected filters are not part of this dashboard",
        )
    resolved: dict[str, str] = {}
    for filter_id, value in selected_filters.items():
        filter_config = by_id[filter_id]
        if value not in filter_config.options:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"The selected value is not available for filter {filter_config.label!r}",
            )
        resolved[filter_config.field] = value
    if not resolved:
        return dashboard

    for widget in dashboard.widgets:
        relevant = {field: value for field, value in resolved.items() if field in widget.columns}
        if not relevant:
            continue
        widget.rows = [
            row for row in widget.rows
            if all(_display(row.get(field)) == value for field, value in relevant.items())
        ]
        widget.row_count = len(widget.rows)
    return dashboard


def _display(value: object) -> str:
    if value is None:
        return "—"
    return str(value)
