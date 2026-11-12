from pydantic import BaseModel


class SystemStatusResponse(BaseModel):
    database: str
    openrouter_configured: bool
    configured_model_count: int
