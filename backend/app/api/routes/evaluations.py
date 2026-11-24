from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.agents.tender_extractor import StructuredLLM
from app.api.dependencies import get_llm, get_session_factory_dep, require_reviewer
from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationFailedError
from app.database.session import get_db
from app.schemas.evaluations import EvaluationOut, RequirementOut
from app.schemas.requirements import ConfirmRequirementsRequest
from app.services import tender_service as svc

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def _out(db: Session, ev) -> EvaluationOut:  # noqa: ANN001
    out = EvaluationOut.model_validate(ev)
    out.requirements = [RequirementOut.model_validate(r) for r in svc.list_requirements(db, ev.id)]
    return out


@router.post("", response_model=EvaluationOut, status_code=status.HTTP_202_ACCEPTED)
async def create_evaluation(
    background: BackgroundTasks,
    name: str = Form(...),
    tender: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    llm: StructuredLLM = Depends(get_llm),
    session_factory: Callable[[], Session] = Depends(get_session_factory_dep),
) -> EvaluationOut:
    content = await tender.read(settings.max_upload_bytes + 1)  # bounded read
    if len(content) > settings.max_upload_bytes:
        raise ValidationFailedError(f"File exceeds {settings.max_upload_mb} MB")
    ev = svc.create_evaluation(db, settings, name, tender.filename or "tender.pdf", content)
    db.commit()  # the background extraction uses its own session and must see the evaluation
    background.add_task(svc.run_extraction, session_factory, llm, ev.id)
    return _out(db, ev)


@router.get("/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(evaluation_id: str, db: Session = Depends(get_db)) -> EvaluationOut:
    return _out(db, svc.get_evaluation(db, evaluation_id))


@router.post("/{evaluation_id}/requirements/confirm", response_model=EvaluationOut)
def confirm_requirements(
    evaluation_id: str,
    body: ConfirmRequirementsRequest,
    reviewer_id: str = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> EvaluationOut:
    ev = svc.confirm_requirements(db, evaluation_id, reviewer_id, body)
    return _out(db, ev)


@router.get("", response_model=list[dict])
def list_evaluations(db: Session = Depends(get_db)) -> list[dict]:
    return svc.list_evaluation_summaries(db)
