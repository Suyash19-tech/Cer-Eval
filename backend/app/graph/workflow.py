"""LangGraph orchestration of the certification-first workflow.

    load_context -> [screen_vendor x N in parallel via Send] -> merge_screening -> generate_certification_report
        -> (PASS vendors not yet evaluated) -> [vendor_downstream x M via Send] -> check_pending
        -> PENDING vendors? -> human_review (interrupt) -> merge_screening -> report -> ... (loop)
        -> finalize

Structural guarantees: the certification report node precedes every downstream node; downstream is reachable only from
the PASS routing edge and re-reads eligibility from the database on entry; FAIL and PENDING vendors have no edge into it.
"""

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("LANGSMITH_TRACING", "false")  # never ship traces/documents to an external service
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Send, interrupt  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.evaluation.config import load_config  # noqa: E402
from app.graph.state import VendorBranchOutput, VendorBranchState, WorkflowState  # noqa: E402
from app.models import Document, Evaluation, Vendor  # noqa: E402
from app.rag.service import RagService  # noqa: E402
from app.reporting.certification_report import write_report  # noqa: E402
from app.schemas.enums import EligibilityStatus, WorkflowStatus  # noqa: E402
from app.services import vendor_service  # noqa: E402
from app.services.tender_service import audit  # noqa: E402

logger = logging.getLogger(__name__)
PASS = EligibilityStatus.PASS.value
PENDING = EligibilityStatus.PENDING_HUMAN_REVIEW.value

Evaluator = Callable[[Session, str, str], dict]  # (db, evaluation_id, vendor_id) -> JSON-serialisable result


class GateViolation(RuntimeError):
    """Raised if downstream evaluation is ever attempted for a vendor that has not PASSed certification."""


@dataclass
class WorkflowDeps:
    session_factory: Callable[[], Session]
    llm: Any
    rag: RagService
    reports_dir: Path
    technical: Evaluator | None = None  # Phase 9 plugs real evaluators in here
    commercial: Evaluator | None = None
    screen_fn: Callable[..., None] | None = None  # override for tests
    model_lock: threading.Lock = field(default_factory=threading.Lock)  # one llama.cpp context: serialise inference


def _log(node: str, status: str = "ok", **extra: Any) -> list[dict]:
    return [{"node": node, "status": status, "ts": datetime.now(timezone.utc).isoformat(), **extra}]


def build_workflow(deps: WorkflowDeps, checkpointer: Any):  # noqa: ANN201
    def with_db(fn: Callable[[Session], Any]) -> Any:
        db = deps.session_factory()
        try:
            out = fn(db)
            db.commit()
            return out
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def set_status(evaluation_id: str, status: WorkflowStatus, action: str) -> None:
        def f(db: Session) -> None:
            ev = db.get(Evaluation, evaluation_id)
            ev.workflow_status = status.value
            audit(db, "workflow", action, evaluation_id, {"status": status.value})
        with_db(f)

    def read_vendor(vendor_id: str, evaluation_id: str) -> dict:
        def f(db: Session) -> dict:
            v = vendor_service.get_vendor(db, evaluation_id, vendor_id)
            return {"name": v.name, "eligibility": v.eligibility, "reason": v.eligibility_reason,
                    "screening_status": v.screening_status, "screening_error": v.screening_error}
        return with_db(f)

    # ---------------- parent nodes ----------------
    def load_context(state: WorkflowState) -> dict:
        eid = state["evaluation_id"]

        def f(db: Session) -> list[str]:
            ev = db.get(Evaluation, eid)
            if ev is None:
                raise ValueError("Unknown evaluation")
            if ev.requirements_confirmed_at is None:
                raise ValueError("Tender requirements are not confirmed; workflow cannot start")
            ids = list(db.scalars(select(Vendor.id).where(Vendor.evaluation_id == eid).order_by(Vendor.name)))
            if not ids:
                raise ValueError("No vendors have been submitted")
            return ids
        ids = with_db(f)
        set_status(eid, WorkflowStatus.RUNNING, "workflow.started")
        return {"vendor_ids": ids, "status": "RUNNING", "node_log": _log("load_context", vendors=len(ids))}

    def fan_out_screening(state: WorkflowState) -> list[Send]:
        return [Send("screen_vendor", {"evaluation_id": state["evaluation_id"], "vendor_id": v, "as_of": state.get("as_of")})
                for v in state["vendor_ids"]]

    def merge_screening(state: WorkflowState) -> dict:
        """Single source of truth for eligibility is the database; refresh state from it (also used after review)."""
        results = {v: {"screening": read_vendor(v, state["evaluation_id"])} for v in state["vendor_ids"]}
        return {"vendor_results": results, "node_log": _log("merge_screening")}

    def generate_certification_report(state: WorkflowState) -> dict:
        path = with_db(lambda db: write_report(db, state["evaluation_id"], deps.reports_dir))
        with_db(lambda db: audit(db, "workflow", "report.certification.generated", state["evaluation_id"], {"file": path.name}))
        return {"certification_reports": [str(path)], "node_log": _log("generate_certification_report", file=path.name)}

    def route_downstream(state: WorkflowState) -> list[Send] | str:
        done = set(state.get("downstream_done", []))
        sends = [Send("vendor_downstream", {"evaluation_id": state["evaluation_id"], "vendor_id": v,
                                            "as_of": state.get("as_of")})
                 for v in state["vendor_ids"]
                 if state["vendor_results"].get(v, {}).get("screening", {}).get("eligibility") == PASS and v not in done]
        return sends or "check_pending"

    def check_pending(state: WorkflowState) -> dict:
        return {"node_log": _log("check_pending")}

    def route_pending(state: WorkflowState) -> str:
        pending = [v for v in state["vendor_ids"]
                   if state["vendor_results"].get(v, {}).get("screening", {}).get("eligibility") == PENDING]
        return "human_review" if pending else "finalize"

    def human_review(state: WorkflowState) -> dict:
        pending = [{"vendor_id": v, "name": r["screening"]["name"], "reason": r["screening"]["reason"]}
                   for v, r in state["vendor_results"].items() if r.get("screening", {}).get("eligibility") == PENDING]
        set_status(state["evaluation_id"], WorkflowStatus.AWAITING_HUMAN_REVIEW, "workflow.awaiting_human_review")
        # Pauses here until a reviewer resumes. The resume value carries no decision: decisions are made through the
        # authenticated review endpoint and read back from the database. Pending can never be coerced to PASS.
        resume = interrupt({"type": "human_review", "pending_vendors": pending})
        set_status(state["evaluation_id"], WorkflowStatus.RUNNING, "workflow.resumed")
        return {"node_log": _log("human_review", resumed_by=(resume or {}).get("reviewer"))}

    def finalize(state: WorkflowState) -> dict:
        eid = state["evaluation_id"]
        set_status(eid, WorkflowStatus.COMPLETED, "workflow.completed")
        return {"status": "COMPLETED", "node_log": _log("finalize")}

    # ---------------- vendor screening branch ----------------
    def verify_documents(state: VendorBranchState) -> dict:
        eid, vid = state["evaluation_id"], state["vendor_id"]

        def f(db: Session) -> int:
            vendor_service.get_vendor(db, eid, vid)
            return db.query(Document).filter(Document.vendor_id == vid).count()
        n = with_db(f)
        return {"node_log": _log("verify_documents", vendor_id=vid, documents=n)}

    def screen_certificates(state: VendorBranchState) -> dict:
        eid, vid = state["evaluation_id"], state["vendor_id"]
        as_of = date.fromisoformat(state["as_of"]) if state.get("as_of") else None
        fn = deps.screen_fn
        if fn is None:
            def fn(sf, llm, rag, e, v, a):  # noqa: ANN001, ANN202
                with deps.model_lock:  # inference is serialised; DB/IO work around it still overlaps
                    vendor_service.screen_vendor(sf, llm, rag, e, v, a)
        fn(deps.session_factory, deps.llm, deps.rag, eid, vid, as_of)
        info = read_vendor(vid, eid)
        errors = [f"{info['name']}: screening failed: {info['screening_error']}"] if info["screening_status"] == "FAILED" else []
        return {"vendor_results": {vid: {"screening": info}}, "errors": errors,
                "node_log": _log("screen_certificates", vendor_id=vid, eligibility=info["eligibility"])}

    # ---------------- PASS-only downstream branch ----------------
    def _assert_pass(eid: str, vid: str, stage: str) -> None:
        info = read_vendor(vid, eid)  # re-read from the database: state alone is never trusted for the gate
        if info["eligibility"] != PASS:
            raise GateViolation(f"{stage} attempted for vendor {vid} with eligibility {info['eligibility']}")

    def _stage(state: VendorBranchState, name: str, other: str, fn: Evaluator | None, ok_statuses: set[str]) -> dict:
        eid, vid = state["evaluation_id"], state["vendor_id"]
        _assert_pass(eid, vid, f"{name} evaluation")
        results = state.get("vendor_results", {}).get(vid, {})
        cfg = with_db(lambda db: load_config(db.get(Evaluation, eid).evaluation_config))
        prior = results.get(other)
        if (prior and cfg.order != "independent" and cfg.second_stage_requires_first_qualified
                and prior.get("status") == "NOT_QUALIFIED"):
            result = {"status": "SKIPPED", "reason": f"{other} evaluation did not qualify this vendor (configured dependency)"}
        elif fn is None:
            result = {"status": "NOT_CONFIGURED"}
        else:
            result = with_db(lambda db: fn(db, eid, vid))
        out: dict = {"vendor_results": {vid: {name: result}}, "node_log": _log(f"{name}_evaluation", vendor_id=vid,
                                                                              result=result.get("status"))}
        if other in results:
            out["downstream_done"] = [vid]
        return out

    def technical_evaluation(state: VendorBranchState) -> dict:
        return _stage(state, "technical", "commercial", deps.technical, {"QUALIFIED"})

    def commercial_evaluation(state: VendorBranchState) -> dict:
        return _stage(state, "commercial", "technical", deps.commercial, {"VALID"})

    def first_stage(state: VendorBranchState) -> str:
        cfg = with_db(lambda db: load_config(db.get(Evaluation, state["evaluation_id"]).evaluation_config))
        return "commercial_evaluation" if cfg.order == "commercial_first" else "technical_evaluation"

    def after_technical(state: VendorBranchState) -> str:
        return END if "commercial" in state.get("vendor_results", {}).get(state["vendor_id"], {}) else "commercial_evaluation"

    def after_commercial(state: VendorBranchState) -> str:
        return END if "technical" in state.get("vendor_results", {}).get(state["vendor_id"], {}) else "technical_evaluation"

    screen = StateGraph(VendorBranchState, output_schema=VendorBranchOutput)
    screen.add_node("verify_documents", verify_documents)
    screen.add_node("screen_certificates", screen_certificates)
    screen.add_edge(START, "verify_documents")
    screen.add_edge("verify_documents", "screen_certificates")
    screen.add_edge("screen_certificates", END)

    downstream = StateGraph(VendorBranchState, output_schema=VendorBranchOutput)
    downstream.add_node("technical_evaluation", technical_evaluation)
    downstream.add_node("commercial_evaluation", commercial_evaluation)
    downstream.add_conditional_edges(START, first_stage, ["technical_evaluation", "commercial_evaluation"])
    downstream.add_conditional_edges("technical_evaluation", after_technical, ["commercial_evaluation", END])
    downstream.add_conditional_edges("commercial_evaluation", after_commercial, ["technical_evaluation", END])

    g = StateGraph(WorkflowState)
    g.add_node("load_context", load_context)
    g.add_node("screen_vendor", screen.compile())
    g.add_node("merge_screening", merge_screening)
    g.add_node("generate_certification_report", generate_certification_report)
    g.add_node("vendor_downstream", downstream.compile())
    g.add_node("check_pending", check_pending)
    g.add_node("human_review", human_review)
    g.add_node("finalize", finalize)
    g.add_edge(START, "load_context")
    g.add_conditional_edges("load_context", fan_out_screening, ["screen_vendor"])
    g.add_edge("screen_vendor", "merge_screening")
    g.add_edge("merge_screening", "generate_certification_report")
    g.add_conditional_edges("generate_certification_report", route_downstream, ["vendor_downstream", "check_pending"])
    g.add_edge("vendor_downstream", "check_pending")
    g.add_conditional_edges("check_pending", route_pending, ["human_review", "finalize"])
    g.add_edge("human_review", "merge_screening")  # refresh from DB -> regenerate report -> newly PASSed vendors proceed
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def with_real_evaluators(deps: WorkflowDeps) -> WorkflowDeps:
    """Plug in the Phase 9 evaluators (local Granite + vendor-scoped RAG)."""
    from app.evaluation import engine

    deps.technical = lambda db, e, v: engine.run_technical(db, e, v, deps.rag, deps.llm, deps.model_lock)
    deps.commercial = lambda db, e, v: engine.run_commercial(db, e, v, deps.rag, deps.llm, deps.model_lock)
    return deps
