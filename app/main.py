from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import dashboard, leads, properties
from app.api.routes.health import router as health_router
from app.api.routes.webhooks import router as webhook_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.getLogger("app").setLevel(logging.INFO)
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(properties.router, prefix="/properties", tags=["properties"])
    app.include_router(leads.router, prefix="/leads", tags=["leads"])
    app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
    return app


app = create_app()
