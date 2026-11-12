from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardGenerationRequest, DashboardResponse
from app.services.dashboard import DashboardService, ExecutedWidget, assemble_dashboard
from app.services.text_to_sql import (
    LLMOutputError,
    TextToSQLService,
    execute_validated_sql,
    load_query_context,
    validate_for_user,
)
from app.sql.validation import SQLPolicyError

router = APIRouter(tags=["dashboards"])


@router.post("/dashboards/generate", response_model=DashboardResponse)
async def generate_dashboard(
    payload: DashboardGenerationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DashboardResponse:
    context = load_query_context(db, user, payload.database_id, payload.company_mapping_id)
    planner = DashboardService(settings)
    sql_service = TextToSQLService(settings)
    try:
        plan, _plan_usage = await planner.create_plan(context, payload.question)
    except LLMOutputError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model returned dashboard JSON that did not match the required format",
        ) from None

    executed_widgets: list[ExecutedWidget] = []
    for widget_plan in plan.widgets:
        try:
            generated, _generated_validation, _selected = await sql_service.generate(
                context, widget_plan.question
            )
        except SQLPolicyError as exc:
            raise _policy_error(exc) from None
        except LLMOutputError:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "The language model could not generate a valid query for every dashboard widget",
            ) from None

        if generated.needs_clarification or not generated.sql:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Dashboard widget '{widget_plan.title}' needs a clearer business question",
            )

        # Recheck access and company scope after model calls, then execute only validated SQL.
        try:
            latest_context, validation = validate_for_user(
                db,
                user,
                payload.database_id,
                generated.sql,
                payload.company_mapping_id,
                settings,
            )
        except SQLPolicyError as exc:
            raise _policy_error(exc) from None
        columns, rows, truncated = await run_in_threadpool(
            execute_validated_sql, latest_context, validation, settings
        )
        executed_widgets.append(
            ExecutedWidget(
                plan=widget_plan,
                sql=validation.sql,
                explanation=generated.explanation or "Validated SQL query results.",
                columns=columns,
                rows=rows,
                truncated=truncated,
            )
        )

    # A database grant can change while multiple dashboard queries are running.
    load_query_context(db, user, payload.database_id, context.company_mapping.id if context.company_mapping else None)

    return assemble_dashboard(
        database_id=payload.database_id,
        company_mapping_id=context.company_mapping.id if context.company_mapping else None,
        question=payload.question,
        plan=plan,
        executed_widgets=executed_widgets,
    )


def _policy_error(exc: SQLPolicyError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": "A dashboard query failed the read-only policy checks",
            "issues": exc.issues,
        },
    )
