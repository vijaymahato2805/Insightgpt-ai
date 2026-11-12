from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models.user import User
from app.schemas.analysis import InsightRequest, InsightResponse
from app.services.insights import BusinessInsightService
from app.services.text_to_sql import (
    LLMOutputError,
    TextToSQLService,
    execute_validated_sql,
    load_query_context,
    validate_for_user,
)
from app.sql.validation import SQLPolicyError

router = APIRouter(prefix="/insights", tags=["business insights"])


@router.post("/generate", response_model=InsightResponse)
async def generate_insights(
    payload: InsightRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InsightResponse:
    context = load_query_context(db, user, payload.database_id, payload.company_mapping_id)
    try:
        generated, _, _ = await TextToSQLService(settings).generate(context, payload.question)
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    except LLMOutputError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model could not prepare a safe query for insight analysis",
        ) from None
    if generated.needs_clarification or not generated.sql:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            generated.clarification or "Please clarify the analysis question",
        )

    try:
        latest_context, validation = validate_for_user(
            db,
            user,
            payload.database_id,
            generated.sql,
            context.company_mapping.id if context.company_mapping else None,
            settings,
        )
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    columns, rows, truncated = await run_in_threadpool(
        execute_validated_sql, latest_context, validation, settings
    )

    try:
        response = await BusinessInsightService(settings).analyze(
            database_id=payload.database_id,
            company_mapping_id=latest_context.company_mapping.id
            if latest_context.company_mapping
            else None,
            company_name=latest_context.company_label,
            request=payload,
            sql=validation.sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )
    except LLMOutputError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model returned an invalid insight response",
        ) from None
    except ValueError as exc:
        message = str(exc)
        if message == "No query rows are available to analyze":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message) from None
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model returned an insight without valid result evidence",
        ) from None

    # Keep access valid through the complete insight request.
    load_query_context(
        db,
        user,
        payload.database_id,
        latest_context.company_mapping.id if latest_context.company_mapping else None,
    )
    return response


def _policy_error(exc: SQLPolicyError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "SQL failed the read-only policy checks", "issues": exc.issues},
    )
