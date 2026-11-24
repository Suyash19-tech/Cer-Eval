"""Starts, resumes and inspects the LangGraph workflow for an evaluation (thread_id == evaluation_id)."""

import logging
import os
from collections.abc import Callable
from typing import Any

from langgraph.types import Command
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models import Evaluation
from app.schemas.enums import WorkflowStatus
from app.services.tender_service import audit

logger = logging.getLogger(__name__)


MAX_CONCURRENCY = int(os.environ.get("HAL_WORKFLOW_MAX_CONCURRENCY", "4"))  # vendors processed in parallel


def _cfg(evaluation_id: str) -> dict:
    return {"configurable": {"thread_id": evaluation_id}, "max_concurrency": MAX_CONCURRENCY}


def snapshot(graph: Any, evaluation_id: str) -> dict:
    snap = graph.get_state(_cfg(evaluation_id))
    values = snap.values or {}
    interrupts = [i.value for t in snap.tasks for i in getattr(t, "interrupts", ())]
    return {
        "started": bool(values), "status": values.get("status"), "waiting_for": list(snap.next),
        "awaiting_human_review": "human_review" in snap.next,
        "pending_review": interrupts[0]["pending_vendors"] if interrupts else [],
        "vendor_results": values.get("vendor_results", {}), "downstream_done": values.get("downstream_done", []),
        "certification_reports": values.get("certification_reports", []), "errors": values.get("errors", []),
        "node_log": values.get("node_log", []),
    }


def assert_can_start(graph: Any, evaluation_id: str) -> None:
    if snapshot(graph, evaluation_id)["started"]:
        raise ConflictError("Workflow already started for this evaluation")


def assert_can_resume(graph: Any, evaluation_id: str) -> None:
    if not snapshot(graph, evaluation_id)["awaiting_human_review"]:
        raise ConflictError("Workflow is not waiting for human review")


def assert_can_retry(graph: Any, evaluation_id: str) -> None:
    snap = snapshot(graph, evaluation_id)
    if not snap["started"] or not snap["waiting_for"] or snap["awaiting_human_review"]:
        raise ConflictError("Nothing to retry: the workflow is not interrupted by an error")


def run(graph: Any, session_factory: Callable[[], Session], evaluation_id: str, payload: Any) -> None:
    """Blocking execution (called from a background task). Failures are recorded, never swallowed silently."""
    try:
        graph.invoke(payload, _cfg(evaluation_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("workflow failed")
        db = session_factory()
        try:
            ev = db.get(Evaluation, evaluation_id)
            if ev:
                ev.workflow_status, ev.error = WorkflowStatus.FAILED.value, f"{type(exc).__name__}: {exc}"[:500]
                audit(db, "workflow", "workflow.failed", evaluation_id, {"error": ev.error})
            db.commit()
        finally:
            db.close()


def start_payload(evaluation_id: str, as_of: str | None) -> dict:
    return {"evaluation_id": evaluation_id, "as_of": as_of}


def resume_payload(reviewer_id: str) -> Command:
    return Command(resume={"reviewer": reviewer_id})
