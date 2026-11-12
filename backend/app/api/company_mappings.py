from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database.session import get_db
from app.models.erp import BusinessDictionaryEntry, CompanyMapping, DatabaseConnection
from app.models.user import User
from app.schemas.erp import CompanyMappingList, CompanyMappingResponse, CompanyMappingWrite
from app.services.database_access import (
    accessible_connections,
    get_connection_for_user,
    require_admin,
)

router = APIRouter(prefix="/company-mappings", tags=["company mappings"])


@router.get("", response_model=CompanyMappingList)
def list_company_mappings(
    database_connection_id: UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CompanyMappingList:
    if database_connection_id:
        get_connection_for_user(db, user, database_connection_id)
        query = select(CompanyMapping).where(
            CompanyMapping.database_connection_id == database_connection_id
        )
    else:
        connection_ids = [item.id for item in accessible_connections(db, user)]
        query = select(CompanyMapping).where(
            CompanyMapping.database_connection_id.in_(connection_ids)
        )
    query = query.order_by(CompanyMapping.company_name)
    return CompanyMappingList(
        items=[CompanyMappingResponse.model_validate(item) for item in db.scalars(query)]
    )


@router.post("", response_model=CompanyMappingResponse, status_code=status.HTTP_201_CREATED)
def create_company_mapping(
    payload: CompanyMappingWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CompanyMappingResponse:
    require_admin(user)
    connection = db.get(DatabaseConnection, payload.database_connection_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    mapping = CompanyMapping(
        database_connection_id=connection.id,
        company_name=payload.company_name,
        erp_version=connection.erp_version,
        table_mappings=payload.table_mappings,
        field_mappings=payload.field_mappings,
        currency_code=payload.currency_code,
        is_auto_generated=False,
    )
    db.add(mapping)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A mapping already exists for this company and connection"
        ) from None
    db.refresh(mapping)
    return CompanyMappingResponse.model_validate(mapping)


@router.put("/{mapping_id}", response_model=CompanyMappingResponse)
def update_company_mapping(
    mapping_id: UUID,
    payload: CompanyMappingWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CompanyMappingResponse:
    require_admin(user)
    mapping = db.get(CompanyMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company mapping not found")
    if payload.database_connection_id != mapping.database_connection_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A mapping cannot be moved to another connection"
        )
    mapping.company_name = payload.company_name
    mapping.table_mappings = payload.table_mappings
    mapping.field_mappings = payload.field_mappings
    mapping.currency_code = payload.currency_code
    mapping.is_auto_generated = False
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A mapping already exists for this company and connection"
        ) from None
    db.refresh(mapping)
    return CompanyMappingResponse.model_validate(mapping)


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company_mapping(
    mapping_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_admin(user)
    mapping = db.get(CompanyMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company mapping not found")
    db.execute(
        delete(BusinessDictionaryEntry).where(
            BusinessDictionaryEntry.company_mapping_id == mapping_id
        )
    )
    db.delete(mapping)
    db.commit()
