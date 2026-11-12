from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConversationFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=240)

    @field_validator("field", "value")
    @classmethod
    def strip_text(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("filter field and value must not be blank")
        return result


class ConversationAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID | None = None
    database_id: UUID | None = None
    company_mapping_id: UUID | None = None
    question: str = Field(min_length=3, max_length=2000)
    active_filters: list[ConversationFilter] | None = Field(default=None, max_length=20)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("question must not be blank")
        return result

    @model_validator(mode="after")
    def new_conversation_needs_database(self) -> "ConversationAskRequest":
        if self.conversation_id is None and self.database_id is None:
            raise ValueError("database_id is required when starting a conversation")
        return self

    @field_validator("active_filters")
    @classmethod
    def unique_filter_fields(
        cls, values: list[ConversationFilter] | None
    ) -> list[ConversationFilter] | None:
        if values is None:
            return None
        keys = {_field_key(item.field) for item in values}
        if len(keys) != len(values):
            raise ValueError("active_filters must not repeat a field")
        return values


class ConversationMessageResponse(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    sql: str | None = None
    result_columns: list[str]
    result_rows: list[dict[str, object]]
    row_count: int
    truncated: bool
    created_at: datetime


class ConversationSummary(BaseModel):
    id: UUID
    database_connection_id: UUID
    company_mapping_id: UUID | None = None
    title: str
    active_filters: list[ConversationFilter]
    updated_at: datetime
    message_count: int


class ConversationList(BaseModel):
    items: list[ConversationSummary]


class ConversationResponse(ConversationSummary):
    messages: list[ConversationMessageResponse]


class InsightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID
    company_mapping_id: UUID | None = None
    question: str = Field(min_length=3, max_length=2000)
    max_insights: int = Field(default=5, ge=1, le=8)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        return _nonempty(value, "question")


class InsightEvidencePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0, le=49)
    field: str = Field(min_length=1, max_length=256)


class InsightItemPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    observation: str = Field(min_length=1, max_length=1000)
    direction: Literal["up", "down", "flat", "notable", "caution"]
    evidence: list[InsightEvidencePlan] = Field(min_length=1, max_length=5)


class InsightPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1500)
    insights: list[InsightItemPlan] = Field(min_length=1, max_length=8)


class InsightEvidence(BaseModel):
    field: str
    value: object


class BusinessInsight(BaseModel):
    title: str
    observation: str
    direction: Literal["up", "down", "flat", "notable", "caution"]
    evidence: list[InsightEvidence]


class InsightResponse(BaseModel):
    database_id: UUID
    company_mapping_id: UUID | None = None
    company_name: str | None = None
    question: str
    sql: str
    columns: list[str]
    row_count: int
    truncated: bool
    summary: str
    insights: list[BusinessInsight]


class PeriodComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID
    company_mapping_id: UUID | None = None
    question: str = Field(min_length=3, max_length=2000)
    date_field: str = Field(min_length=1, max_length=160)
    metric_field: str = Field(min_length=1, max_length=160)
    dimension_fields: list[str] = Field(default_factory=list, max_length=6)
    current_start: date
    current_end: date
    comparison_start: date
    comparison_end: date

    @field_validator("question", "date_field", "metric_field")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        return _nonempty(value, "comparison input")

    @field_validator("dimension_fields")
    @classmethod
    def normalize_dimensions(cls, values: list[str]) -> list[str]:
        cleaned = [_nonempty(item, "dimension field") for item in values]
        if len({_field_key(item) for item in cleaned}) != len(cleaned):
            raise ValueError("dimension_fields must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_periods(self) -> "PeriodComparisonRequest":
        if self.current_start > self.current_end or self.comparison_start > self.comparison_end:
            raise ValueError("period start must be on or before its end")
        if not (
            self.current_end < self.comparison_start
            or self.comparison_end < self.current_start
        ):
            raise ValueError("comparison periods must not overlap")
        return self


class PeriodComparisonRow(BaseModel):
    dimensions: dict[str, object]
    current_value: str | None
    comparison_value: str | None
    absolute_change: str | None
    percentage_change: str | None


class PeriodComparisonResponse(BaseModel):
    database_id: UUID
    company_mapping_id: UUID | None = None
    currency_code: str | None = None
    question: str
    date_field: str
    metric_field: str
    dimension_fields: list[str]
    current_start: date
    current_end: date
    comparison_start: date
    comparison_end: date
    rows: list[PeriodComparisonRow]


class CompanyComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID
    company_mapping_ids: list[UUID] = Field(min_length=2, max_length=5)
    question: str = Field(min_length=3, max_length=2000)
    metric_field: str = Field(min_length=1, max_length=160)
    dimension_fields: list[str] = Field(default_factory=list, max_length=6)
    currency_fields: list[str] = Field(default_factory=list, max_length=10)
    target_currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    exchange_rates: dict[str, Decimal] = Field(default_factory=dict, max_length=8)

    @field_validator("question", "metric_field")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        return _nonempty(value, "comparison input")

    @field_validator("dimension_fields", "currency_fields")
    @classmethod
    def normalize_field_lists(cls, values: list[str]) -> list[str]:
        cleaned = [_nonempty(item, "field name") for item in values]
        if len({_field_key(item) for item in cleaned}) != len(cleaned):
            raise ValueError("field lists must not contain duplicates")
        return cleaned

    @field_validator("target_currency_code")
    @classmethod
    def normalize_target_currency(cls, value: str | None) -> str | None:
        return _currency_code(value) if value is not None else None

    @field_validator("exchange_rates")
    @classmethod
    def normalize_rates(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        normalized: dict[str, Decimal] = {}
        for code, rate in value.items():
            currency = _currency_code(code)
            if rate <= 0:
                raise ValueError("exchange rates must be greater than zero")
            normalized[currency] = rate
        return normalized

    @model_validator(mode="after")
    def unique_companies(self) -> "CompanyComparisonRequest":
        if len(set(self.company_mapping_ids)) != len(self.company_mapping_ids):
            raise ValueError("company_mapping_ids must be unique")
        return self


class CompanyResult(BaseModel):
    company_mapping_id: UUID
    company_name: str
    source_currency_code: str | None = None
    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int
    truncated: bool


class CompanyDelta(BaseModel):
    absolute_change: str
    percentage_change: str | None


class CompanyComparisonRow(BaseModel):
    dimensions: dict[str, object]
    values_by_company: dict[str, str | None]
    changes_vs_baseline: dict[str, CompanyDelta]


class CompanyComparisonResponse(BaseModel):
    database_id: UUID
    question: str
    metric_field: str
    dimension_fields: list[str]
    baseline_company: str
    target_currency_code: str | None = None
    currency_fields: list[str]
    companies: list[CompanyResult]
    rows: list[CompanyComparisonRow]


def _currency_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency codes must be three letters")
    return code


def _nonempty(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    return normalized


def _field_key(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())
