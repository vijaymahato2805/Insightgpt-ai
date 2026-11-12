from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models.erp import Conversation, ConversationMessage
from app.models.user import User
from app.schemas.analysis import (
    ConversationAskRequest,
    ConversationFilter,
    ConversationList,
    ConversationMessageResponse,
    ConversationResponse,
    ConversationSummary,
)
from app.services.comparisons import ComparisonInputError, apply_conversation_filters
from app.services.conversation_memory import contextualize_question
from app.services.database_access import accessible_connections
from app.services.text_to_sql import (
    LLMOutputError,
    TextToSQLService,
    execute_validated_sql,
    load_query_context,
    validate_for_user,
)
from app.sql.validation import SQLPolicyError

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/ask", response_model=ConversationResponse)
async def ask_follow_up(
    payload: ConversationAskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationResponse:
    conversation = None
    if payload.conversation_id:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == payload.conversation_id,
                Conversation.user_id == user.id,
            )
        )
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        if payload.database_id and payload.database_id != conversation.database_connection_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A follow-up must use the conversation's original database",
            )
        if payload.company_mapping_id and payload.company_mapping_id != conversation.company_mapping_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A follow-up must use the conversation's original company scope",
            )
        database_id = conversation.database_connection_id
        company_mapping_id = conversation.company_mapping_id
        active_filters = (
            [item.model_dump() for item in payload.active_filters]
            if payload.active_filters is not None
            else list(conversation.active_filters or [])
        )
        messages = _load_messages(db, conversation.id, descending=False)
    else:
        database_id = payload.database_id
        company_mapping_id = payload.company_mapping_id
        active_filters = [item.model_dump() for item in payload.active_filters or []]
        messages = []

    assert database_id is not None
    context = load_query_context(db, user, database_id, company_mapping_id)
    conversation_scope_id = context.company_mapping.id if context.company_mapping else None
    query_question = contextualize_question(payload.question, active_filters, messages)
    service = TextToSQLService(settings)
    try:
        generated, _, _ = await service.generate(context, query_question)
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    except LLMOutputError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model returned an invalid response for this follow-up",
        ) from None

    generated.question = payload.question
    columns: list[str] = []
    rows: list[dict[str, object]] = []
    row_count = 0
    truncated = False
    if generated.needs_clarification or not generated.sql:
        # Access is rechecked even when the model asks for clarification.
        load_query_context(db, user, database_id, conversation_scope_id)
        answer = generated.clarification or "Please clarify the question."
    else:
        try:
            filtered_sql = apply_conversation_filters(
                context, generated.sql, active_filters
            )
            latest_context, validation = validate_for_user(
                db,
                user,
                database_id,
                filtered_sql,
                conversation_scope_id,
                settings,
            )
        except SQLPolicyError as exc:
            raise _policy_error(exc) from None
        except ComparisonInputError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
        columns, rows, truncated = await run_in_threadpool(
            execute_validated_sql, latest_context, validation, settings
        )
        load_query_context(db, user, database_id, conversation_scope_id)
        generated.sql = validation.sql
        row_count = len(rows)
        answer = generated.explanation or "The query completed successfully."

    if conversation is None:
        conversation = Conversation(
            user_id=user.id,
            database_connection_id=database_id,
            company_mapping_id=conversation_scope_id,
            title=payload.question[:160],
            active_filters=active_filters,
        )
        db.add(conversation)
        db.flush()
    else:
        conversation.active_filters = active_filters
        conversation.updated_at = datetime.now(UTC)

    db.add_all(
        [
            ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content=payload.question,
            ),
            ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=answer,
                sql=generated.sql,
                result_columns=columns,
                result_rows=rows[:20],
                row_count=row_count,
                truncated=truncated,
            ),
        ]
    )
    db.commit()
    db.refresh(conversation)
    return _conversation_response(db, conversation)


@router.get("", response_model=ConversationList)
def list_conversations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ConversationList:
    accessible_ids = {
        item.id for item in accessible_connections(db, user) if item.enabled
    }
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(
                Conversation.user_id == user.id,
                Conversation.database_connection_id.in_(accessible_ids),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        )
    )
    visible_conversations = []
    for conversation in conversations:
        try:
            load_query_context(
                db,
                user,
                conversation.database_connection_id,
                conversation.company_mapping_id,
            )
        except HTTPException:
            continue
        visible_conversations.append(conversation)
    return ConversationList(
        items=[_conversation_summary(db, item) for item in visible_conversations]
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conversation = _get_owned_conversation(db, user, conversation_id)
    load_query_context(
        db, user, conversation.database_connection_id, conversation.company_mapping_id
    )
    return _conversation_response(db, conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    conversation = _get_owned_conversation(db, user, conversation_id)
    load_query_context(
        db, user, conversation.database_connection_id, conversation.company_mapping_id
    )
    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _load_messages(
    db: Session, conversation_id: UUID, *, descending: bool, limit: int = 100
) -> list[ConversationMessage]:
    order = (
        (ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
        if descending
        else (ConversationMessage.created_at, ConversationMessage.id)
    )
    messages = list(
        db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(*order)
            .limit(limit)
        )
    )
    return list(reversed(messages)) if descending else messages


def _conversation_summary(db: Session, conversation: Conversation) -> ConversationSummary:
    message_count = db.scalar(
        select(func.count(ConversationMessage.id)).where(
            ConversationMessage.conversation_id == conversation.id
        )
    ) or 0
    return ConversationSummary(
        id=conversation.id,
        database_connection_id=conversation.database_connection_id,
        company_mapping_id=conversation.company_mapping_id,
        title=conversation.title,
        active_filters=[ConversationFilter.model_validate(item) for item in conversation.active_filters],
        updated_at=conversation.updated_at,
        message_count=message_count,
    )


def _conversation_response(db: Session, conversation: Conversation) -> ConversationResponse:
    summary = _conversation_summary(db, conversation)
    return ConversationResponse(
        **summary.model_dump(),
        messages=[
            ConversationMessageResponse.model_validate(message, from_attributes=True)
            for message in _load_messages(db, conversation.id, descending=True)
        ],
    )


def _get_owned_conversation(db: Session, user: User, conversation_id: UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


def _policy_error(exc: SQLPolicyError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "SQL failed the read-only policy checks", "issues": exc.issues},
    )
