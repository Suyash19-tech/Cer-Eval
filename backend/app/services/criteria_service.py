"""Tender criteria: extraction (background) and human confirmation. Mirrors the requirement-confirmation rules."""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.criteria_extractor import extract_criteria
from app.agents.tender_extractor import StructuredLLM
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.evaluation.config import load_config
from app.models import Evaluation, EvaluationCriterion
from app.agents.tender_extractor import normalize
from app.schemas.criteria import COMMERCIAL_PARAMS, ConfirmCriteriaRequest, ManualCriterion
from app.schemas.documents import PageText
from app.services.tender_service import audit, get_evaluation

logger = logging.getLogger(__name__)


def start_extraction(db: Session, evaluation_id: str) -> Evaluation:
    ev = get_evaluation(db, evaluation_id)
    if ev.requirements_confirmed_at is None:
        raise ConflictError("Confirm the certification requirements first")
    if ev.criteria_status in ("EXTRACTING", "CONFIRMED"):
        raise ConflictError(f"Criteria are already {ev.criteria_status}")
    ev.criteria_status = "EXTRACTING"
    db.flush()
    return ev


def run_extraction(session_factory: Callable[[], Session], llm: StructuredLLM, evaluation_id: str) -> None:
    db = session_factory()
    try:
        ev = db.get(Evaluation, evaluation_id)
        pages = [PageText(**p) for p in (ev.tender_pages or [])]
        items = extract_criteria(llm, pages)
        db.execute(delete(EvaluationCriterion).where(EvaluationCriterion.evaluation_id == evaluation_id))
        for it in items:
            db.add(EvaluationCriterion(evaluation_id=evaluation_id, confirmed=False, origin="LLM", **it))
        ev.criteria_status = "PENDING_CONFIRMATION"
        audit(db, "system", "criteria.extracted", evaluation_id, {"count": len(items)})
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("criteria extraction failed")
        db.rollback()
        ev = db.get(Evaluation, evaluation_id)
        ev.criteria_status, ev.error = "FAILED", f"criteria extraction: {type(exc).__name__}: {exc}"[:500]
        db.commit()
    finally:
        db.close()


def list_criteria(db: Session, evaluation_id: str) -> list[EvaluationCriterion]:
    return list(db.scalars(select(EvaluationCriterion).where(EvaluationCriterion.evaluation_id == evaluation_id)
                           .order_by(EvaluationCriterion.criterion_code)))


def add_manual_criterion(db: Session, evaluation_id: str, reviewer_id: str, body: ManualCriterion) -> EvaluationCriterion:
    ev = get_evaluation(db, evaluation_id)
    if ev.criteria_status != "PENDING_CONFIRMATION":
        raise ConflictError(f"Criteria are {ev.criteria_status}; criteria can be added only while awaiting confirmation")
    if body.comparator == "CONTAINS":
        if not (body.required_text or "").strip():
            raise ValidationFailedError("A CONTAINS criterion needs required_text")
    elif body.required_value is None:
        raise ValidationFailedError("A numeric criterion needs required_value")
    if body.kind == "COMMERCIAL":
        if body.parameter is not None and body.parameter not in COMMERCIAL_PARAMS:
            raise ValidationFailedError(f"parameter must be one of {COMMERCIAL_PARAMS}")
    elif body.parameter is not None:
        raise ValidationFailedError("Only commercial criteria have a parameter")
    # grounding: the quoted sentence must exist in the tender text, exactly as for extracted criteria
    needle = normalize(body.supporting_text)
    page = next((p["page_number"] for p in (ev.tender_pages or []) if needle in normalize(p["text"])), None)
    if page is None:
        raise ValidationFailedError("supporting_text was not found verbatim in the tender")
    prefix = "TECH" if body.kind == "TECHNICAL" else "COM"
    nums = [int(r.criterion_code.split("-")[1]) for r in list_criteria(db, evaluation_id)
            if r.criterion_code.startswith(prefix + "-")]
    row = EvaluationCriterion(
        evaluation_id=evaluation_id, criterion_code=f"{prefix}-{max(nums, default=0) + 1:03d}", kind=body.kind, name=body.name,
        parameter=body.parameter, comparator=body.comparator.value, required_value=body.required_value,
        required_text=body.required_text, unit=body.unit, mandatory=body.mandatory, weight=body.weight, source_page=page,
        supporting_text=body.supporting_text, needs_human_review=False, review_reasons=None, confirmed=False,
        rejected=False, origin="HUMAN")
    db.add(row)
    audit(db, reviewer_id, "criterion.added_manually", evaluation_id,
          {"criterion": row.criterion_code, "reason": body.reason, "page": page})
    db.flush()
    return row


def confirm_criteria(db: Session, evaluation_id: str, reviewer_id: str, body: ConfirmCriteriaRequest) -> Evaluation:
    ev = get_evaluation(db, evaluation_id)
    if ev.criteria_status != "PENDING_CONFIRMATION":
        raise ConflictError(f"Criteria are {ev.criteria_status}, not awaiting confirmation")
    rows = {r.criterion_code: r for r in list_criteria(db, evaluation_id)}
    decisions = {d.criterion_code: d for d in body.decisions}
    unknown = set(decisions) - set(rows)
    if unknown:
        raise NotFoundError(f"Unknown criteria: {sorted(unknown)}")
    try:
        cfg = load_config(body.config)
    except ValueError as exc:
        raise ValidationFailedError(f"Invalid evaluation config: {exc}") from exc
    unresolved = [c for c, r in rows.items() if r.needs_human_review and c not in decisions]
    if unresolved:
        raise ValidationFailedError(f"Flagged criteria need an explicit decision: {unresolved}")
    for code, r in rows.items():
        d = decisions.get(code)
        if d and d.action == "reject":
            if not d.reason:
                raise ValidationFailedError(f"{code}: a reason is required to reject")
            r.rejected, r.confirmed = True, False
            continue
        if d and d.action == "edit":
            if d.edit is None:
                raise ValidationFailedError(f"{code}: edit decision without edit")
            for k, v in d.edit.model_dump(exclude_unset=True).items():
                setattr(r, k, v.value if hasattr(v, "value") else v)
            if r.comparator != "CONTAINS" and r.required_value is None:
                raise ValidationFailedError(f"{code}: numeric criterion needs a required value")
            if r.comparator == "CONTAINS" and not r.required_text:
                raise ValidationFailedError(f"{code}: CONTAINS criterion needs required text")
        r.confirmed, r.rejected = True, False
    ev.evaluation_config = cfg.model_dump()
    ev.criteria_status = "CONFIRMED"
    audit(db, reviewer_id, "criteria_confirmed", evaluation_id,
          {"accepted": sum(1 for r in rows.values() if r.confirmed), "rejected": sum(1 for r in rows.values() if r.rejected),
           "config": ev.evaluation_config, "at": datetime.now(timezone.utc).isoformat()})
    db.flush()
    return ev


