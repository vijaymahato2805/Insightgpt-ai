from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sql.contracts import QueryResult, TextToSQLResult, TokenUsage


class SQLQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID
    question: str = Field(min_length=3, max_length=4000)
    company_mapping_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class SQLInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: UUID
    sql: str = Field(min_length=1, max_length=20000)
    company_mapping_id: UUID | None = None

    @field_validator("sql")
    @classmethod
    def trim_sql(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("sql must not be blank")
        return value


class SQLExplanationRequest(SQLInputRequest):
    question: str | None = Field(default=None, max_length=4000)


class SQLValidationResponse(BaseModel):
    database_id: UUID
    valid: bool = True
    sql: str
    tables: list[str]
    columns: list[str]
    max_rows: int


class SQLGenerationResponse(TextToSQLResult):
    pass


class SQLChatResponse(QueryResult):
    pass


class SQLExecutionResponse(BaseModel):
    database_id: UUID
    sql: str
    tables: list[str]
    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int
    truncated: bool
    max_rows: int


class SQLExplainResponse(BaseModel):
    database_id: UUID
    sql: str
    explanation: str
    notes: list[str] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
