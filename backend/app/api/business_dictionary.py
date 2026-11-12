from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database.session import get_db
from app.models.erp import BusinessDictionaryEntry, CompanyMapping, DatabaseConnection
from app.models.user import User
from app.schemas.erp import (
    BusinessDictionaryList,
    BusinessDictionaryResponse,
    BusinessDictionaryWrite,
)
from app.services.database_access import (
    accessible_connections,
    get_connection_for_user,
    require_admin,
)

router = APIRouter(prefix="/business-dictionary", tags=["business dictionary"])


def _validate_scope(db: Session, payload: BusinessDictionaryWrite) -> None:
    if (
        payload.database_connection_id
        and db.get(DatabaseConnection, payload.database_connection_id) is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    if payload.company_mapping_id:
        mapping = db.get(CompanyMapping, payload.company_mapping_id)
        if mapping is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Company mapping not found")
        if (
            payload.database_connection_id
            and payload.database_connection_id != mapping.database_connection_id
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Company mapping and dictionary entry must use the same database connection",
            )
        if payload.database_connection_id is None:
            payload.database_connection_id = mapping.database_connection_id


def _check_duplicate(
    db: Session, payload: BusinessDictionaryWrite, exclude_id: UUID | None = None
) -> None:
    query = select(BusinessDictionaryEntry.id).where(
        func.lower(BusinessDictionaryEntry.term) == payload.term.casefold(),
        BusinessDictionaryEntry.database_connection_id == payload.database_connection_id,
        BusinessDictionaryEntry.company_mapping_id == payload.company_mapping_id,
    )
    if exclude_id:
        query = query.where(BusinessDictionaryEntry.id != exclude_id)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That term already exists in this scope")


@router.get("", response_model=BusinessDictionaryList)
def list_business_dictionary(
    database_connection_id: UUID | None = None,
    company_mapping_id: UUID | None = None,
    include_disabled: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BusinessDictionaryList:
    mapping_connection_id = None
    if database_connection_id:
        get_connection_for_user(db, user, database_connection_id)
    if company_mapping_id:
        mapping = db.get(CompanyMapping, company_mapping_id)
        if mapping is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Company mapping not found")
        get_connection_for_user(db, user, mapping.database_connection_id)
        mapping_connection_id = mapping.database_connection_id
        if database_connection_id and database_connection_id != mapping.database_connection_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Company mapping scope does not match"
            )
    query = select(BusinessDictionaryEntry)
    if database_connection_id:
        query = query.where(
            (BusinessDictionaryEntry.database_connection_id.is_(None))
            | (BusinessDictionaryEntry.database_connection_id == database_connection_id)
        )
    elif company_mapping_id:
        query = query.where(
            (BusinessDictionaryEntry.database_connection_id.is_(None))
            | (BusinessDictionaryEntry.database_connection_id == mapping_connection_id)
        )
    else:
        # General terms plus entries from connections the current user can see.
        connection_ids = [item.id for item in accessible_connections(db, user)]
        query = query.where(
            (BusinessDictionaryEntry.database_connection_id.is_(None))
            | (BusinessDictionaryEntry.database_connection_id.in_(connection_ids))
        )
    if company_mapping_id:
        query = query.where(
            (BusinessDictionaryEntry.company_mapping_id.is_(None))
            | (BusinessDictionaryEntry.company_mapping_id == company_mapping_id)
        )
    if not include_disabled:
        query = query.where(BusinessDictionaryEntry.enabled.is_(True))
    query = query.order_by(BusinessDictionaryEntry.term)
    return BusinessDictionaryList(
        items=[BusinessDictionaryResponse.model_validate(item) for item in db.scalars(query)]
    )


@router.post("", response_model=BusinessDictionaryResponse, status_code=status.HTTP_201_CREATED)
def create_business_dictionary_entry(
    payload: BusinessDictionaryWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BusinessDictionaryResponse:
    require_admin(user)
    _validate_scope(db, payload)
    _check_duplicate(db, payload)
    entry = BusinessDictionaryEntry(
        term=payload.term,
        definition=payload.definition,
        entry_type=payload.entry_type.value,
        database_connection_id=payload.database_connection_id,
        company_mapping_id=payload.company_mapping_id,
        enabled=payload.enabled,
        created_by=user.id,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not create dictionary entry") from None
    db.refresh(entry)
    return BusinessDictionaryResponse.model_validate(entry)


@router.put("/{entry_id}", response_model=BusinessDictionaryResponse)
def update_business_dictionary_entry(
    entry_id: UUID,
    payload: BusinessDictionaryWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BusinessDictionaryResponse:
    require_admin(user)
    entry = db.get(BusinessDictionaryEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business dictionary entry not found")
    _validate_scope(db, payload)
    _check_duplicate(db, payload, exclude_id=entry_id)
    entry.term = payload.term
    entry.definition = payload.definition
    entry.entry_type = payload.entry_type.value
    entry.database_connection_id = payload.database_connection_id
    entry.company_mapping_id = payload.company_mapping_id
    entry.enabled = payload.enabled
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not update dictionary entry") from None
    db.refresh(entry)
    return BusinessDictionaryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business_dictionary_entry(
    entry_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_admin(user)
    entry = db.get(BusinessDictionaryEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business dictionary entry not found")
    db.delete(entry)
    db.commit()
