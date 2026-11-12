from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth,
    business_dictionary,
    company_mappings,
    comparisons,
    conversations,
    dashboards,
    databases,
    insights,
    saved_dashboards,
    schema,
    sql,
    system,
)
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Enterprise natural language analytics platform API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth.router, prefix="/api")
app.include_router(databases.router, prefix="/api")
app.include_router(schema.router, prefix="/api")
app.include_router(company_mappings.router, prefix="/api")
app.include_router(business_dictionary.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(sql.router, prefix="/api")
app.include_router(dashboards.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(comparisons.router, prefix="/api")
app.include_router(saved_dashboards.router, prefix="/api")
