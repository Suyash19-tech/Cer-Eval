from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import evaluation_stage, evaluations, health, reports, vendors, workflow
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.database.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="HAL Vendor Certification Screening", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(evaluations.router, prefix="/api")
    app.include_router(vendors.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(workflow.router, prefix="/api")
    app.include_router(evaluation_stage.router, prefix="/api")
    return app


app = create_app()
