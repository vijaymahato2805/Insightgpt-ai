from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Visualization = Literal["kpi", "bar", "line", "area", "pie", "donut", "table"]


class DashboardFilterPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    field_hint: str = Field(min_length=1, max_length=120)


class DashboardWidgetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=120)
    visualization: Visualization
    question: str = Field(min_length=3, max_length=1000)
    layout_span: Literal[1, 2, 4] = 2
    category_field_hint: str | None = Field(default=None, max_length=120)
    value_field_hint: str | None = Field(default=None, max_length=120)
    series_field_hint: str | None = Field(default=None, max_length=120)
    drilldown_field_hint: str | None = Field(default=None, max_length=120)


class DashboardPlan(BaseModel):
    """Strict contract for the JSON returned by the dashboard planning model."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    filters: list[DashboardFilterPlan] = Field(default_factory=list, max_length=4)
    widgets: list[DashboardWidgetPlan] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_ids(self) -> "DashboardPlan":
        widget_ids = [item.widget_id for item in self.widgets]
        filter_ids = [item.filter_id for item in self.filters]
        if len(widget_ids) != len(set(widget_ids)):
            raise ValueError("widget_id values must be unique")
        if len(filter_ids) != len(set(filter_ids)):
            raise ValueError("filter_id values must be unique")
        normalized_filter_fields = [item.field_hint.casefold().strip() for item in self.filters]
        if len(normalized_filter_fields) != len(set(normalized_filter_fields)):
            raise ValueError("Dashboard filters must use unique result fields")
        return self


class DashboardFilter(BaseModel):
    filter_id: str
    label: str
    field: str
    options: list[str]


class DashboardWidget(BaseModel):
    widget_id: str
    title: str
    visualization: Visualization
    question: str
    layout_span: Literal[1, 2, 4]
    sql: str
    explanation: str
    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int
    truncated: bool
    category_field: str | None = None
    value_field: str | None = None
    series_field: str | None = None
    drilldown_field: str | None = None


class DashboardResponse(BaseModel):
    database_id: UUID
    company_mapping_id: UUID | None = None
    question: str
    title: str
    description: str
    filters: list[DashboardFilter]
    widgets: list[DashboardWidget]


class DashboardGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID
    company_mapping_id: UUID | None = None
    question: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def trim_question(self) -> "DashboardGenerationRequest":
        question = self.question.strip()
        if not question:
            raise ValueError("question must not be blank")
        self.question = question
        return self


class SavedDashboardFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    field: str = Field(min_length=1, max_length=256)


class SavedDashboardWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=120)
    visualization: Visualization
    question: str = Field(min_length=3, max_length=1000)
    layout_span: Literal[1, 2, 4]
    sql: str = Field(min_length=1, max_length=20000)
    explanation: str = Field(default="", max_length=2000)
    category_field: str | None = Field(default=None, max_length=256)
    value_field: str | None = Field(default=None, max_length=256)
    series_field: str | None = Field(default=None, max_length=256)
    drilldown_field: str | None = Field(default=None, max_length=256)


class SavedDashboardDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID
    company_mapping_id: UUID | None = None
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    question: str = Field(min_length=3, max_length=2000)
    filters: list[SavedDashboardFilterConfig] = Field(default_factory=list, max_length=4)
    widgets: list[SavedDashboardWidgetConfig] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_ids_and_text(self) -> "SavedDashboardDefinition":
        self.title = self.title.strip()
        self.question = self.question.strip()
        if not self.title or not self.question:
            raise ValueError("title and question must not be blank")
        widget_ids = [item.widget_id for item in self.widgets]
        filter_ids = [item.filter_id for item in self.filters]
        if len(widget_ids) != len(set(widget_ids)):
            raise ValueError("widget_id values must be unique")
        if len(filter_ids) != len(set(filter_ids)):
            raise ValueError("filter_id values must be unique")
        normalized_filter_fields = [item.field.casefold().strip() for item in self.filters]
        if len(normalized_filter_fields) != len(set(normalized_filter_fields)):
            raise ValueError("Dashboard filters must use unique result fields")
        return self


class SavedDashboardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    dashboard: SavedDashboardDefinition


class SavedDashboardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dashboard: SavedDashboardDefinition


class SavedDashboardFavoriteWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_favorite: bool


class SavedDashboardSummary(BaseModel):
    id: UUID
    database_id: UUID
    company_mapping_id: UUID | None = None
    title: str
    question: str
    is_favorite: bool
    current_version: int
    created_at: str
    updated_at: str


class SavedDashboardList(BaseModel):
    items: list[SavedDashboardSummary]


class DashboardVersionSummary(BaseModel):
    version_number: int
    title: str
    created_by: UUID
    created_at: str


class DashboardVersionList(BaseModel):
    dashboard_id: UUID
    current_version: int
    items: list[DashboardVersionSummary]
