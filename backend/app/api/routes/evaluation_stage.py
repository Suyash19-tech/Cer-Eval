"""Criteria extraction/confirmation, evaluation results, criterion review and stage reports."""

from collections.abc import Callable
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.tender_extractor import StructuredLLM
from app.api.dependencies import get_llm, get_session_factory_dep, require_reviewer
from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.database.session import get_db
from app.evaluation import engine
from app.models import CommercialSummary, CriterionFinding, ReviewDecision
from app.reporting import evaluation_reports as rep
from app.schemas.criteria import ConfirmCriteriaRequest, CriterionOut, ManualCriterion
from app.services import criteria_service as svc
from app.services import vendor_service
from app.services.tender_service import audit, get_evaluation

router = APIRouter(prefix="/evaluations/{evaluation_id}", tags=["evaluation"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/criteria/extract", status_code=status.HTTP_202_ACCEPTED)
def extract(evaluation_id: str, background: BackgroundTasks, db: Session = Depends(get_db),
            llm: StructuredLLM = Depends(get_llm),
            session_factory: Callable[[], Session] = Depends(get_session_factory_dep)) -> dict:
    svc.start_extraction(db, evaluation_id)
    db.commit()
    background.add_task(svc.run_extraction, session_factory, llm, evaluation_id)
    return {"criteria_status": "EXTRACTING"}


@router.get("/criteria")
def criteria(evaluation_id: str, db: Session = Depends(get_db)) -> dict:
    ev = get_evaluation(db, evaluation_id)
    return {"criteria_status": ev.criteria_status, "config": ev.evaluation_config,
            "criteria": [CriterionOut.model_validate(c).model_dump() for c in svc.list_criteria(db, evaluation_id)]}


@router.post("/criteria", status_code=status.HTTP_201_CREATED)
def add_criterion(evaluation_id: str, body: ManualCriterion, reviewer_id: str = Depends(require_reviewer),
                  db: Session = Depends(get_db)) -> dict:
    return CriterionOut.model_validate(svc.add_manual_criterion(db, evaluation_id, reviewer_id, body)).model_dump()


@router.post("/criteria/confirm")
def confirm(evaluation_id: str, body: ConfirmCriteriaRequest, reviewer_id: str = Depends(require_reviewer),
            db: Session = Depends(get_db)) -> dict:
    ev = svc.confirm_criteria(db, evaluation_id, reviewer_id, body)
    return {"criteria_status": ev.criteria_status, "config": ev.evaluation_config}


class CriterionReview(BaseModel):
    criterion_code: str
    decision: Literal["MEETS", "DEVIATES"]
    reason: str = Field(min_length=10)


@router.post("/vendors/{vendor_id}/criteria/review")
def review_criterion(evaluation_id: str, vendor_id: str, body: CriterionReview,
                     reviewer_id: str = Depends(require_reviewer), db: Session = Depends(get_db)) -> dict:
    vendor = vendor_service.get_vendor(db, evaluation_id, vendor_id)
    if vendor.eligibility != "PASS":
        raise ConflictError("Only certification-qualified vendors have evaluation findings")
    f = db.scalars(select(CriterionFinding).where(CriterionFinding.vendor_id == vendor_id,
                                                  CriterionFinding.criterion_code == body.criterion_code)).first()
    if f is None:
        raise NotFoundError("Finding not found")
    if f.status not in ("NEEDS_HUMAN_REVIEW", "MISSING_DETAIL"):
        raise ConflictError("Only findings awaiting human review can be resolved")
    db.add(ReviewDecision(evaluation_id=evaluation_id, vendor_id=vendor_id, requirement_code=body.criterion_code,
                          decision=body.decision, reviewer_id=reviewer_id, reason=body.reason,
                          evidence=str((f.evidence or {}).get("supporting_text")), previous_status=f.status,
                          new_status=body.decision))
    f.status, f.resolved_by = body.decision, reviewer_id
    audit(db, reviewer_id, "criterion.reviewed", evaluation_id, {"vendor_id": vendor_id, "criterion": body.criterion_code})
    db.flush()
    return {"technical": engine.technical_result(db, evaluation_id, vendor_id),
            "commercial": engine.commercial_result(db, evaluation_id, vendor_id)}


class SummaryReview(BaseModel):
    reason: str = Field(min_length=10)


@router.post("/vendors/{vendor_id}/commercial/approve")
def approve_commercial_summary(evaluation_id: str, vendor_id: str, body: SummaryReview,
                               reviewer_id: str = Depends(require_reviewer), db: Session = Depends(get_db)) -> dict:
    vendor_service.get_vendor(db, evaluation_id, vendor_id)
    s = db.get(CommercialSummary, vendor_id)
    if s is None or not s.needs_human_review:
        raise ConflictError("Nothing to approve")
    db.add(ReviewDecision(evaluation_id=evaluation_id, vendor_id=vendor_id, requirement_code="COMMERCIAL_SUMMARY",
                          decision="APPROVED", reviewer_id=reviewer_id, reason=body.reason,
                          evidence="; ".join(s.review_reasons or []), previous_status="NEEDS_HUMAN_REVIEW", new_status="APPROVED"))
    s.needs_human_review = False
    audit(db, reviewer_id, "commercial_summary.approved", evaluation_id, {"vendor_id": vendor_id})
    db.flush()
    return engine.commercial_result(db, evaluation_id, vendor_id)


@router.get("/results")
def results(evaluation_id: str, db: Session = Depends(get_db)) -> dict:
    get_evaluation(db, evaluation_id)
    rows = engine.build_results(db, evaluation_id)
    return {"vendors": [asdict(r) for r in rows],
            "ranking": [r.vendor_id for r in sorted((r for r in rows if r.ranked), key=lambda x: x.rank)]}


def _report(kind: str, builder, evaluation_id: str, db: Session, settings: Settings) -> FileResponse:  # noqa: ANN001
    get_evaluation(db, evaluation_id)
    path = rep.save(builder(db, evaluation_id), settings.reports_dir, evaluation_id, kind)
    audit(db, "system", f"report.{kind}.generated", evaluation_id, {"file": path.name})
    return FileResponse(path, media_type=XLSX, filename=path.name)


@router.get("/reports/technical")
def technical_report(evaluation_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):  # noqa: ANN201
    return _report("technical_evaluation", rep.build_technical, evaluation_id, db, settings)


@router.get("/reports/commercial")
def commercial_report(evaluation_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):  # noqa: ANN201
    return _report("commercial_evaluation", rep.build_commercial, evaluation_id, db, settings)


@router.get("/reports/consolidated")
def consolidated_report(evaluation_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):  # noqa: ANN201
    return _report("consolidated_comparison", rep.build_consolidated, evaluation_id, db, settings)


@router.get("/evaluation-details")
def evaluation_details(evaluation_id: str, db: Session = Depends(get_db)) -> dict:
    """Findings and commercial summaries (exist only for certification-qualified vendors) for the UI."""
    from app.models import EvaluationCriterion, Vendor

    get_evaluation(db, evaluation_id)
    vendors = {v.id: v for v in db.scalars(select(Vendor).where(Vendor.evaluation_id == evaluation_id))}
    crit = {c.criterion_code: c for c in db.scalars(select(EvaluationCriterion).where(
        EvaluationCriterion.evaluation_id == evaluation_id))}
    findings = []
    for f in db.scalars(select(CriterionFinding).where(CriterionFinding.evaluation_id == evaluation_id)
                        .order_by(CriterionFinding.criterion_code)):
        c = crit.get(f.criterion_code)
        findings.append({"vendor_id": f.vendor_id, "vendor_name": vendors[f.vendor_id].name, "kind": f.kind,
                         "criterion_code": f.criterion_code, "name": c.name if c else f.criterion_code,
                         "comparator": c.comparator if c else None, "required_value": c.required_value if c else None,
                         "required_text": c.required_text if c else None, "unit": c.unit if c else None,
                         "tender_page": c.source_page if c else None, "mandatory": f.mandatory, "weight": f.weight,
                         "status": f.status, "reasons": f.reasons or [], "evidence": f.evidence or {},
                         "resolved_by": f.resolved_by})
    summaries = [{"vendor_id": s.vendor_id, "vendor_name": vendors[s.vendor_id].name, "data": s.data,
                  "needs_human_review": s.needs_human_review, "review_reasons": s.review_reasons or []}
                 for s in db.scalars(select(CommercialSummary).where(CommercialSummary.evaluation_id == evaluation_id))]
    return {"findings": findings, "commercial": summaries}
