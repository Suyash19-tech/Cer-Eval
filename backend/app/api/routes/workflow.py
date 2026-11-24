from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_session_factory_dep, get_workflow_graph, require_reviewer
from app.database.session import get_db
from app.services import workflow_service as ws
from app.services.tender_service import audit, get_evaluation

router = APIRouter(prefix="/evaluations/{evaluation_id}/workflow", tags=["workflow"])


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
def start(evaluation_id: str, background: BackgroundTasks, as_of: date | None = None,
          db: Session = Depends(get_db), graph=Depends(get_workflow_graph),  # noqa: ANN001
          session_factory: Callable[[], Session] = Depends(get_session_factory_dep)) -> dict:
    get_evaluation(db, evaluation_id)
    ws.assert_can_start(graph, evaluation_id)
    db.commit()  # make vendors/docs visible to the background thread's own session
    background.add_task(ws.run, graph, session_factory, evaluation_id,
                        ws.start_payload(evaluation_id, as_of.isoformat() if as_of else None))
    return {"evaluation_id": evaluation_id, "accepted": True}


@router.post("/resume", status_code=status.HTTP_202_ACCEPTED)
def resume(evaluation_id: str, background: BackgroundTasks, reviewer_id: str = Depends(require_reviewer),
           db: Session = Depends(get_db), graph=Depends(get_workflow_graph),  # noqa: ANN001
           session_factory: Callable[[], Session] = Depends(get_session_factory_dep)) -> dict:
    get_evaluation(db, evaluation_id)
    ws.assert_can_resume(graph, evaluation_id)
    audit(db, reviewer_id, "workflow.resume_requested", evaluation_id)
    db.commit()
    background.add_task(ws.run, graph, session_factory, evaluation_id, ws.resume_payload(reviewer_id))
    return {"evaluation_id": evaluation_id, "accepted": True}


@router.post("/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(evaluation_id: str, background: BackgroundTasks, reviewer_id: str = Depends(require_reviewer),
          db: Session = Depends(get_db), graph=Depends(get_workflow_graph),  # noqa: ANN001
          session_factory: Callable[[], Session] = Depends(get_session_factory_dep)) -> dict:
    """Error recovery: continue from the last checkpoint after a failed node (completed branches are not repeated)."""
    ev = get_evaluation(db, evaluation_id)
    ws.assert_can_retry(graph, evaluation_id)
    ev.error = None
    audit(db, reviewer_id, "workflow.retry_requested", evaluation_id)
    db.commit()
    background.add_task(ws.run, graph, session_factory, evaluation_id, None)  # None = continue from checkpoint
    return {"evaluation_id": evaluation_id, "accepted": True}


@router.get("")
def get_workflow(evaluation_id: str, db: Session = Depends(get_db), graph=Depends(get_workflow_graph)) -> dict:  # noqa: ANN001
    ev = get_evaluation(db, evaluation_id)
    out = ws.snapshot(graph, evaluation_id)
    out.update(evaluation_id=evaluation_id, workflow_status=ev.workflow_status, error=ev.error)
    return out
