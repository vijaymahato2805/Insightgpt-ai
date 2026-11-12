from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models.user import User
from app.schemas.sql import (
    SQLChatResponse,
    SQLExecutionResponse,
    SQLExplainResponse,
    SQLExplanationRequest,
    SQLGenerationResponse,
    SQLInputRequest,
    SQLQuestionRequest,
    SQLValidationResponse,
)
from app.services.text_to_sql import (
    LLMOutputError,
    TextToSQLService,
    execute_validated_sql,
    load_query_context,
    validate_for_user,
)
from app.sql.contracts import QueryResult
from app.sql.validation import SQLPolicyError

router = APIRouter(tags=["text to SQL"])


@router.post("/sql/generate", response_model=SQLGenerationResponse)
async def generate_sql(
    payload: SQLQuestionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SQLGenerationResponse:
    context = load_query_context(db, user, payload.database_id, payload.company_mapping_id)
    result, _, _ = await _generate(context, payload.question, settings)
    return SQLGenerationResponse.model_validate(result.model_dump())


@router.post("/sql/validate", response_model=SQLValidationResponse)
def validate_sql(
    payload: SQLInputRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SQLValidationResponse:
    try:
        _, validation = validate_for_user(
            db,
            user,
            payload.database_id,
            payload.sql,
            payload.company_mapping_id,
            settings,
        )
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    return SQLValidationResponse(
        database_id=payload.database_id,
        sql=validation.sql,
        tables=validation.tables,
        columns=validation.columns,
        max_rows=validation.max_rows,
    )


@router.post("/sql/execute", response_model=SQLExecutionResponse)
def execute_sql(
    payload: SQLInputRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SQLExecutionResponse:
    try:
        context, validation = validate_for_user(
            db,
            user,
            payload.database_id,
            payload.sql,
            payload.company_mapping_id,
            settings,
        )
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    columns, rows, truncated = execute_validated_sql(context, validation, settings)
    return SQLExecutionResponse(
        database_id=payload.database_id,
        sql=validation.sql,
        tables=validation.tables,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        max_rows=settings.sql_max_result_rows,
    )


@router.post("/sql/explain", response_model=SQLExplainResponse)
async def explain_sql(
    payload: SQLExplanationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SQLExplainResponse:
    try:
        context, validation = validate_for_user(
            db,
            user,
            payload.database_id,
            payload.sql,
            payload.company_mapping_id,
            settings,
        )
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    service = TextToSQLService(settings)
    try:
        explanation = await service.explain(context, validation.sql, payload.question)
    except LLMOutputError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model returned an invalid explanation",
        ) from None
    return SQLExplainResponse(
        database_id=payload.database_id,
        sql=validation.sql,
        explanation=explanation.explanation,
        notes=explanation.notes,
        token_usage=service.last_usage.to_schema(),
    )


@router.post("/chat/ask", response_model=SQLChatResponse)
async def ask_question(
    payload: SQLQuestionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SQLChatResponse:
    context = load_query_context(db, user, payload.database_id, payload.company_mapping_id)
    result, _validation, _selected = await _generate(context, payload.question, settings)
    if result.needs_clarification or not result.sql:
        return SQLChatResponse.model_validate(QueryResult(**result.model_dump()).model_dump())

    # Recheck the grant and schema boundary after the asynchronous model calls.
    try:
        latest_context, latest_validation = validate_for_user(
            db,
            user,
            payload.database_id,
            result.sql,
            payload.company_mapping_id,
            settings,
        )
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    columns, rows, truncated = await run_in_threadpool(
        execute_validated_sql, latest_context, latest_validation, settings
    )
    return SQLChatResponse.model_validate(
        {
            **result.model_dump(),
            "sql": latest_validation.sql,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
    )


async def _generate(context, question: str, settings: Settings):
    service = TextToSQLService(settings)
    try:
        return await service.generate(context, question)
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    except LLMOutputError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model returned a response that did not match the required format",
        ) from None


def _policy_error(exc: SQLPolicyError) -> HTTPException:
    return HTTPException(
        422,
        detail={"message": "SQL failed the read-only policy checks", "issues": exc.issues},
    )
