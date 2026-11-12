from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.llm.provider import OpenRouterProvider
from app.schemas.system import SystemStatusResponse

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system/status", response_model=SystemStatusResponse)
def system_status(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SystemStatusResponse:
    try:
        db.execute(text("SELECT 1"))
        database_ready = True
    except SQLAlchemyError:
        database_ready = False
    openrouter_ready, configured_model_count = OpenRouterProvider(settings).configuration_status()
    return SystemStatusResponse(
        database="connected" if database_ready else "unavailable",
        openrouter_configured=openrouter_ready,
        configured_model_count=configured_model_count,
    )
