from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.reporting.certification_report import write_report
from app.services.tender_service import audit, get_evaluation

router = APIRouter(prefix="/evaluations/{evaluation_id}/reports", tags=["reports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/certification")
def certification_report(evaluation_id: str, db: Session = Depends(get_db),
                         settings: Settings = Depends(get_settings)) -> FileResponse:
    get_evaluation(db, evaluation_id)  # 404 if unknown
    path = write_report(db, evaluation_id, settings.reports_dir)
    audit(db, "system", "report.certification.generated", evaluation_id, {"file": path.name})
    return FileResponse(path, media_type=XLSX, filename=path.name)
