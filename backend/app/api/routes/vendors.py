from collections.abc import Callable
from datetime import date

from fastapi.responses import FileResponse
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.agents.tender_extractor import StructuredLLM
from app.api.dependencies import get_intake, get_llm, get_rag, get_session_factory_dep, require_reviewer
from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationFailedError
from app.database.session import get_db
from app.document_processing.service import DocumentIntake
from app.rag.service import RagService
from app.schemas.certificates import FindingOut, ReviewRequest, VendorOut
from app.services import vendor_service as svc

router = APIRouter(prefix="/evaluations/{evaluation_id}/vendors", tags=["vendors"])


def _out(db: Session, v) -> VendorOut:  # noqa: ANN001
    out = VendorOut.model_validate(v)
    out.findings = [FindingOut.model_validate(f) for f in svc.list_findings(db, v.id)]
    return out


@router.post("", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
async def add_vendor(
    evaluation_id: str,
    name: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    rag: RagService = Depends(get_rag),
    intake: DocumentIntake = Depends(get_intake),
) -> VendorOut:
    loaded = []
    for f in files:
        content = await f.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise ValidationFailedError(f"{f.filename}: exceeds {settings.max_upload_mb} MB")
        loaded.append((f.filename or "document", content))
    return _out(db, svc.create_vendor(db, settings, rag, intake, evaluation_id, name, loaded))


@router.get("", response_model=list[VendorOut])
def list_vendors(evaluation_id: str, db: Session = Depends(get_db)) -> list[VendorOut]:
    return [_out(db, v) for v in svc.list_vendors(db, evaluation_id)]


@router.get("/{vendor_id}/documents/{document_id}/file")
def download_document(evaluation_id: str, vendor_id: str, document_id: str, db: Session = Depends(get_db),
                      settings: Settings = Depends(get_settings)) -> FileResponse:
    """Serve an original vendor document for human review. Scoped to the vendor; path confined to the uploads dir."""
    path, mime, name = svc.document_file(db, settings, evaluation_id, vendor_id, document_id)
    return FileResponse(path, media_type=mime, filename=name, content_disposition_type="inline",
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.get("/{vendor_id}", response_model=VendorOut)
def get_vendor(evaluation_id: str, vendor_id: str, db: Session = Depends(get_db)) -> VendorOut:
    return _out(db, svc.get_vendor(db, evaluation_id, vendor_id))


@router.post("/{vendor_id}/screen", response_model=VendorOut, status_code=status.HTTP_202_ACCEPTED)
def screen(
    evaluation_id: str, vendor_id: str, background: BackgroundTasks,
    as_of: date | None = None,
    db: Session = Depends(get_db),
    llm: StructuredLLM = Depends(get_llm),
    rag: RagService = Depends(get_rag),
    session_factory: Callable[[], Session] = Depends(get_session_factory_dep),
) -> VendorOut:
    vendor = svc.get_vendor(db, evaluation_id, vendor_id)
    vendor.screening_status = "SCREENING"
    db.commit()  # make the status visible to (and unlocked for) the background thread's own session
    background.add_task(svc.screen_vendor, session_factory, llm, rag, evaluation_id, vendor_id, as_of)
    return _out(db, vendor)


@router.post("/{vendor_id}/review", response_model=VendorOut)
def review(
    evaluation_id: str, vendor_id: str, body: ReviewRequest,
    reviewer_id: str = Depends(require_reviewer), db: Session = Depends(get_db),
) -> VendorOut:
    v = svc.review_finding(db, evaluation_id, vendor_id, reviewer_id, body.requirement_code, body.decision, body.reason)
    return _out(db, v)
