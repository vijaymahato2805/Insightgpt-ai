from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models.erp import DashboardVersion, SavedDashboard
from app.models.user import User
from app.schemas.dashboard import (
    DashboardResponse,
    DashboardVersionList,
    DashboardVersionSummary,
    SavedDashboardCreate,
    SavedDashboardFavoriteWrite,
    SavedDashboardList,
    SavedDashboardSummary,
    SavedDashboardUpdate,
)
from app.services.dashboard import ExecutedWidget, assemble_dashboard
from app.services.dashboard_exports import export_dashboard
from app.services.database_access import accessible_connections
from app.services.saved_dashboards import (
    apply_selected_filters,
    definition_to_snapshot,
    snapshot_to_plan,
)
from app.services.text_to_sql import execute_validated_sql, load_query_context, validate_for_user
from app.sql.validation import SQLPolicyError

router = APIRouter(prefix="/saved-dashboards", tags=["saved dashboards"])


@router.get("", response_model=SavedDashboardList)
def list_saved_dashboards(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SavedDashboardList:
    allowed_ids = {item.id for item in accessible_connections(db, user) if item.enabled}
    candidates = list(
        db.scalars(
            select(SavedDashboard)
            .where(
                SavedDashboard.user_id == user.id,
                SavedDashboard.database_connection_id.in_(allowed_ids),
            )
            .order_by(SavedDashboard.is_favorite.desc(), SavedDashboard.updated_at.desc())
            .limit(100)
        )
    )
    visible = []
    for item in candidates:
        try:
            load_query_context(db, user, item.database_connection_id, item.company_mapping_id)
        except HTTPException:
            continue
        visible.append(_summary(item))
    return SavedDashboardList(items=visible)


@router.post("", response_model=SavedDashboardSummary, status_code=status.HTTP_201_CREATED)
def create_saved_dashboard(
    payload: SavedDashboardCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SavedDashboardSummary:
    snapshot = _validate_definition(db, user, payload.dashboard, settings)
    dashboard = SavedDashboard(
        user_id=user.id,
        database_connection_id=payload.dashboard.database_id,
        company_mapping_id=payload.dashboard.company_mapping_id,
        title=payload.dashboard.title,
        question=payload.dashboard.question,
        current_version=1,
    )
    db.add(dashboard)
    db.flush()
    db.add(
        DashboardVersion(
            dashboard_id=dashboard.id,
            version_number=1,
            snapshot=snapshot,
            created_by=user.id,
        )
    )
    db.commit()
    db.refresh(dashboard)
    return _summary(dashboard)


@router.get("/{dashboard_id}/versions", response_model=DashboardVersionList)
def list_dashboard_versions(
    dashboard_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardVersionList:
    dashboard = _owned_dashboard(db, user, dashboard_id)
    load_query_context(db, user, dashboard.database_connection_id, dashboard.company_mapping_id)
    versions = list(
        db.scalars(
            select(DashboardVersion)
            .where(DashboardVersion.dashboard_id == dashboard.id)
            .order_by(DashboardVersion.version_number.desc())
            .limit(100)
        )
    )
    return DashboardVersionList(
        dashboard_id=dashboard.id,
        current_version=dashboard.current_version,
        items=[
            DashboardVersionSummary(
                version_number=item.version_number,
                title=item.snapshot["plan"]["title"],
                created_by=item.created_by,
                created_at=_iso(item.created_at),
            )
            for item in versions
        ],
    )


@router.post(
    "/{dashboard_id}/versions/{version_number}/restore",
    response_model=SavedDashboardSummary,
)
def restore_dashboard_version(
    dashboard_id: UUID,
    version_number: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SavedDashboardSummary:
    dashboard = _owned_dashboard(db, user, dashboard_id, lock=True)
    load_query_context(db, user, dashboard.database_connection_id, dashboard.company_mapping_id)
    selected = db.scalar(
        select(DashboardVersion).where(
            DashboardVersion.dashboard_id == dashboard.id,
            DashboardVersion.version_number == version_number,
        )
    )
    if selected is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard version not found")
    snapshot = _validate_snapshot(
        db,
        user,
        dashboard.database_connection_id,
        dashboard.company_mapping_id,
        selected.snapshot,
        settings,
    )
    _append_version(db, dashboard, user, snapshot)
    db.commit()
    db.refresh(dashboard)
    return _summary(dashboard)


@router.patch("/{dashboard_id}/favorite", response_model=SavedDashboardSummary)
def set_dashboard_favorite(
    dashboard_id: UUID,
    payload: SavedDashboardFavoriteWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedDashboardSummary:
    dashboard = _owned_dashboard(db, user, dashboard_id, lock=True)
    load_query_context(db, user, dashboard.database_connection_id, dashboard.company_mapping_id)
    dashboard.is_favorite = payload.is_favorite
    dashboard.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(dashboard)
    return _summary(dashboard)


@router.put("/{dashboard_id}", response_model=SavedDashboardSummary)
def update_saved_dashboard(
    dashboard_id: UUID,
    payload: SavedDashboardUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SavedDashboardSummary:
    dashboard = _owned_dashboard(db, user, dashboard_id, lock=True)
    load_query_context(db, user, dashboard.database_connection_id, dashboard.company_mapping_id)
    if payload.expected_version != dashboard.current_version:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dashboard changed; reload it before saving")
    definition = payload.dashboard
    if (
        definition.database_id != dashboard.database_connection_id
        or definition.company_mapping_id != dashboard.company_mapping_id
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "A saved dashboard cannot change data scope")
    snapshot = _validate_definition(db, user, definition, settings)
    dashboard.title = definition.title
    dashboard.question = definition.question
    dashboard.updated_at = datetime.now(UTC)
    _append_version(db, dashboard, user, snapshot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Dashboard version was created by another request"
        ) from None
    db.refresh(dashboard)
    return _summary(dashboard)


@router.get("/{dashboard_id}/export")
async def export_saved_dashboard(
    dashboard_id: UUID,
    format: str = Query(pattern=r"^(xlsx|pdf)$"),
    version_number: int | None = Query(default=None, ge=1),
    filters: str | None = Query(default=None, max_length=4000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    dashboard = _owned_dashboard(db, user, dashboard_id)
    selected_filters = _parse_filters(filters)
    result = await _render_saved_dashboard(
        db, user, dashboard, settings, version_number, selected_filters
    )
    content, media_type, filename = await run_in_threadpool(
        export_dashboard, result, format, selected_filters
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{dashboard_id}", response_model=DashboardResponse)
async def get_saved_dashboard(
    dashboard_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    filters: str | None = Query(default=None, max_length=4000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DashboardResponse:
    dashboard = _owned_dashboard(db, user, dashboard_id)
    return await _render_saved_dashboard(
        db,
        user,
        dashboard,
        settings,
        version_number,
        _parse_filters(filters),
    )


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_dashboard(
    dashboard_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    dashboard = _owned_dashboard(db, user, dashboard_id)
    load_query_context(db, user, dashboard.database_connection_id, dashboard.company_mapping_id)
    db.delete(dashboard)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _render_saved_dashboard(
    db: Session,
    user: User,
    dashboard: SavedDashboard,
    settings: Settings,
    version_number: int | None,
    selected_filters: dict[str, str],
) -> DashboardResponse:
    load_query_context(db, user, dashboard.database_connection_id, dashboard.company_mapping_id)
    if version_number is None or version_number == dashboard.current_version:
        version = db.scalar(
            select(DashboardVersion).where(
                DashboardVersion.dashboard_id == dashboard.id,
                DashboardVersion.version_number == dashboard.current_version,
            )
        )
    else:
        version = db.scalar(
            select(DashboardVersion).where(
                DashboardVersion.dashboard_id == dashboard.id,
                DashboardVersion.version_number == version_number,
            )
        )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard version not found")
    try:
        plan, queries = snapshot_to_plan(version.snapshot)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_409_CONFLICT, "Saved dashboard configuration is invalid") from None

    executions: list[ExecutedWidget] = []
    for widget_plan in plan.widgets:
        query = queries[widget_plan.widget_id]
        try:
            latest_context, validation = validate_for_user(
                db,
                user,
                dashboard.database_connection_id,
                query["sql"],
                dashboard.company_mapping_id,
                settings,
            )
        except SQLPolicyError as exc:
            raise _policy_error(exc) from None
        columns, rows, truncated = await run_in_threadpool(
            execute_validated_sql, latest_context, validation, settings
        )
        executions.append(
            ExecutedWidget(
                plan=widget_plan,
                sql=validation.sql,
                explanation=query.get("explanation", "Saved validated SQL query."),
                columns=columns,
                rows=rows,
                truncated=truncated,
            )
        )
    load_query_context(db, user, dashboard.database_connection_id, dashboard.company_mapping_id)
    result = assemble_dashboard(
        database_id=dashboard.database_connection_id,
        company_mapping_id=dashboard.company_mapping_id,
        question=version.snapshot["question"],
        plan=plan,
        executed_widgets=executions,
    )
    return apply_selected_filters(result, selected_filters)


def _validate_definition(db: Session, user: User, definition, settings: Settings) -> dict:
    snapshot = definition_to_snapshot(definition)
    return _validate_snapshot(
        db,
        user,
        definition.database_id,
        definition.company_mapping_id,
        snapshot,
        settings,
    )


def _validate_snapshot(
    db: Session,
    user: User,
    database_id: UUID,
    company_mapping_id: UUID | None,
    snapshot: dict,
    settings: Settings,
) -> dict:
    try:
        plan, queries = snapshot_to_plan(snapshot)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Dashboard definition is invalid") from None
    clean_queries = {}
    for widget in plan.widgets:
        query = queries[widget.widget_id]
        try:
            _, validation = validate_for_user(
                db, user, database_id, query["sql"], company_mapping_id, settings
            )
        except SQLPolicyError as exc:
            raise _policy_error(exc) from None
        clean_queries[widget.widget_id] = {
            "sql": validation.sql,
            "explanation": query.get("explanation", ""),
        }
    return {
        "question": snapshot["question"],
        "plan": plan.model_dump(mode="json"),
        "queries": clean_queries,
    }


def _owned_dashboard(
    db: Session, user: User, dashboard_id: UUID, *, lock: bool = False
) -> SavedDashboard:
    query = select(SavedDashboard).where(
        SavedDashboard.id == dashboard_id,
        SavedDashboard.user_id == user.id,
    )
    if lock:
        query = query.with_for_update()
    dashboard = db.scalar(query)
    if dashboard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved dashboard not found")
    return dashboard


def _append_version(db: Session, dashboard: SavedDashboard, user: User, snapshot: dict) -> None:
    next_version = dashboard.current_version + 1
    dashboard.current_version = next_version
    dashboard.title = snapshot["plan"]["title"]
    dashboard.question = snapshot["question"]
    dashboard.updated_at = datetime.now(UTC)
    db.add(
        DashboardVersion(
            dashboard_id=dashboard.id,
            version_number=next_version,
            snapshot=snapshot,
            created_by=user.id,
        )
    )


def _summary(dashboard: SavedDashboard) -> SavedDashboardSummary:
    return SavedDashboardSummary(
        id=dashboard.id,
        database_id=dashboard.database_connection_id,
        company_mapping_id=dashboard.company_mapping_id,
        title=dashboard.title,
        question=dashboard.question,
        is_favorite=dashboard.is_favorite,
        current_version=dashboard.current_version,
        created_at=_iso(dashboard.created_at),
        updated_at=_iso(dashboard.updated_at),
    )


def _parse_filters(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "filters must be a JSON object") from None
    if not isinstance(parsed, dict) or len(parsed) > 4 or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in parsed.items()
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "filters must be a small string map")
    return parsed


def _iso(value: datetime) -> str:
    return value.isoformat()


def _policy_error(exc: SQLPolicyError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "A saved widget query failed the read-only policy checks", "issues": exc.issues},
    )
