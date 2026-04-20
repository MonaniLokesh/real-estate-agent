from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.webhooks import router as webhook_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    logging.getLogger("app").setLevel(logging.INFO)
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.include_router(health_router)
    app.include_router(webhook_router)
    return app


app = create_app()
