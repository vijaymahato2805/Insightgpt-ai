from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=80)
    metrics: list[str] = Field(default_factory=list, max_length=20)
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    filters: list[str] = Field(default_factory=list, max_length=30)
    time_period: str | None = Field(default=None, max_length=160)
    requested_company: str | None = Field(default=None, max_length=160)
    needs_clarification: bool = False
    clarification: str | None = Field(default=None, max_length=1000)


class SchemaSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ids: list[UUID] = Field(default_factory=list, max_length=16)
    reason: str = Field(default="", max_length=1000)


class SQLDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, max_length=20000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class SQLExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1, max_length=5000)
    notes: list[str] = Field(default_factory=list, max_length=20)


class SQLValidationResult(BaseModel):
    sql: str
    tables: list[str]
    columns: list[str]
    max_rows: int


class SQLContextObject(BaseModel):
    id: UUID
    schema_name: str
    object_name: str
    object_type: str
    description: str | None = None
    columns: list[dict[str, str | int | bool | None]]
    relationships: list[dict[str, str | None]] = Field(default_factory=list)


class BusinessTermContext(BaseModel):
    term: str
    definition: str
    entry_type: str
    source: str


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class TextToSQLResult(BaseModel):
    database_id: UUID
    company_mapping_id: UUID | None = None
    question: str
    intent: QueryIntent
    sql: str | None = None
    explanation: str | None = None
    explanation_notes: list[str] = Field(default_factory=list)
    selected_tables: list[str] = Field(default_factory=list)
    business_terms: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class QueryResult(TextToSQLResult):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, object]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
