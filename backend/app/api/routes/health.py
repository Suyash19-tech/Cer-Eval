from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.session import get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    offline_mode: bool
    environment: str


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok", database="ok", offline_mode=settings.offline, environment=settings.env
    )
