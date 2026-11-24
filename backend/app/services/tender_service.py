"""Evaluation creation, requirement extraction persistence and human confirmation."""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.tender_extractor import StructuredLLM, TenderRequirementExtractor, assign_ids, verify
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.document_processing.extractor import extract_document, sha256_of
from app.document_processing.ocr import get_ocr_engine
from app.document_processing.upload_safety import sanitize_filename, validate_upload
from app.models import AuditLog, Evaluation, TenderRequirement
from app.schemas.documents import PageText
from app.schemas.enums import WorkflowStatus
from app.schemas.requirements import ConfirmRequirementsRequest, ExtractedRequirement

logger = logging.getLogger(__name__)


def audit(db: Session, actor: str, action: str, evaluation_id: str | None, detail: dict | None = None) -> None:
    db.add(AuditLog(actor=actor, action=action, evaluation_id=evaluation_id, detail=detail))
    logging.getLogger("hal.audit").info(action, extra={"actor": actor, "evaluation_id": evaluation_id, **(detail or {})})


def get_evaluation(db: Session, evaluation_id: str) -> Evaluation:
    ev = db.get(Evaluation, evaluation_id)
    if ev is None:
        raise NotFoundError(f"Evaluation {evaluation_id} not found")
    return ev


def create_evaluation(db: Session, settings: Settings, name: str, filename: str, content: bytes) -> Evaluation:
    mime = validate_upload(filename, content[:16], len(content), settings.max_upload_bytes)
    if mime != "application/pdf":
        raise ValidationFailedError("The tender must be a PDF")
    ev = Evaluation(name=name.strip()[:255] or "Untitled evaluation", tender_path="", tender_sha256="")
    db.add(ev)
    db.flush()
    folder = settings.uploads_dir / ev.id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("tender_" + sanitize_filename(filename))
    path.write_bytes(content)
    try:
        doc = extract_document(path, mime, _LazyOcr())
    except Exception as exc:
        raise ValidationFailedError("Tender PDF could not be read") from exc
    if not any(p.text for p in doc.pages):
        raise ValidationFailedError("No readable text could be extracted from the tender PDF")
    ev.tender_path, ev.tender_sha256 = str(path), sha256_of(path)
    ev.tender_pages = [p.model_dump() for p in doc.pages]
    ev.workflow_status = WorkflowStatus.EXTRACTING_REQUIREMENTS.value
    audit(db, "system", "evaluation_created", ev.id, {"tender_sha256": ev.tender_sha256})
    db.commit()
    return ev


class _LazyOcr:
    name = "lazy"

    def image_to_text(self, image):  # noqa: ANN001
        return get_ocr_engine().image_to_text(image)


def run_extraction(session_factory: Callable[[], Session], llm: StructuredLLM, evaluation_id: str) -> None:
    """Background job: extract requirements and persist them as UNCONFIRMED."""
    with session_factory() as db:
        ev = get_evaluation(db, evaluation_id)
        try:
            pages = [PageText(**p) for p in ev.tender_pages or []]
            reqs = TenderRequirementExtractor(llm).extract(pages)
            for r in reqs:
                db.add(_to_row(ev.id, r, origin="LLM"))
            ev.workflow_status = WorkflowStatus.REQUIREMENTS_PENDING_CONFIRMATION.value
            audit(db, "system", "requirements_extracted", ev.id, {"count": len(reqs)})
        except Exception as exc:
            logger.exception("requirement extraction failed")
            ev.workflow_status, ev.error = WorkflowStatus.FAILED.value, f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()


def _to_row(evaluation_id: str, r: ExtractedRequirement, origin: str) -> TenderRequirement:
    return TenderRequirement(
        evaluation_id=evaluation_id, requirement_code=r.requirement_id, category=r.category.value,
        description=r.description, mandatory=r.mandatory, certificate_name=r.certificate_name,
        standard=r.standard, version=r.version, validation_conditions={"conditions": r.validation_conditions},
        source_page=r.source_page, supporting_text=r.supporting_text, needs_human_review=r.needs_human_review,
        review_reasons=r.review_reasons, origin=origin,
    )


def list_requirements(db: Session, evaluation_id: str) -> list[TenderRequirement]:
    stmt = select(TenderRequirement).where(TenderRequirement.evaluation_id == evaluation_id).order_by(
        TenderRequirement.requirement_code)
    return list(db.scalars(stmt))


def confirm_requirements(
    db: Session, evaluation_id: str, reviewer_id: str, body: ConfirmRequirementsRequest
) -> Evaluation:
    ev = get_evaluation(db, evaluation_id)
    if ev.workflow_status != WorkflowStatus.REQUIREMENTS_PENDING_CONFIRMATION.value:
        raise ConflictError(f"Requirements cannot be confirmed in status {ev.workflow_status}")
    rows = {r.requirement_code: r for r in list_requirements(db, evaluation_id)}
    decisions = {d.requirement_id: d for d in body.decisions}
    unknown = set(decisions) - set(rows)
    if unknown:
        raise ValidationFailedError(f"Unknown requirement ids: {sorted(unknown)}")
    unresolved = [c for c, r in rows.items() if r.needs_human_review and c not in decisions]
    if unresolved:
        raise ValidationFailedError("Flagged requirements need an explicit decision", {"unresolved": sorted(unresolved)})

    for code, row in rows.items():
        d = decisions.get(code)
        if d and d.action == "reject":
            if not d.reason:
                db.rollback()
                raise ValidationFailedError(f"A reason is required to reject {code}")
            row.rejected = True
        else:
            if d and d.action == "edit":
                if d.edits is None:
                    db.rollback()
                    raise ValidationFailedError(f"Edit decision for {code} has no edits")
                _apply_edits(row, d.edits.model_dump(exclude_unset=True))
            row.confirmed = True
        if d:
            audit(db, reviewer_id, f"requirement_{d.action}", ev.id, {"requirement": code, "reason": d.reason})

    pages = [PageText(**p) for p in ev.tender_pages or []]
    added: list[ExtractedRequirement] = []
    for manual in body.additions:
        item, ok = verify(manual, pages)
        if not ok:  # a manual addition must still be grounded in the tender
            db.rollback()
            raise ValidationFailedError("Manual requirement is not grounded in the tender text", {"issues": item.review_reasons})
        added.append(item)
    counters: dict[str, int] = {}
    for code in rows:
        prefix = code.split("-")[1]
        counters[prefix] = max(counters.get(prefix, 0), int(code.rsplit("-", 1)[1]))
    assign_ids(added, counters)
    for item in added:
        row = _to_row(ev.id, item, origin="MANUAL")
        row.needs_human_review, row.confirmed = False, True
        db.add(row)
        audit(db, reviewer_id, "requirement_added_manually", ev.id, {"requirement": item.requirement_id})

    accepted = [(r.mandatory, r.category) for r in rows.values() if r.confirmed and not r.rejected]
    accepted += [(a.mandatory, a.category.value) for a in added]
    if not any(m and c != "ELIGIBILITY_CONDITION" for m, c in accepted):
        db.rollback()  # discard the edits/decisions applied above
        raise ValidationFailedError("At least one mandatory certification requirement must be confirmed")

    ev.workflow_status = WorkflowStatus.REQUIREMENTS_CONFIRMED.value
    ev.requirements_confirmed_at = datetime.now(timezone.utc)
    ev.requirements_confirmed_by = reviewer_id
    audit(db, reviewer_id, "requirements_confirmed", ev.id, {"accepted": len(accepted)})
    db.commit()
    return ev


def _apply_edits(row: TenderRequirement, edits: dict) -> None:
    for key, value in edits.items():
        if key == "validation_conditions":
            row.validation_conditions = {"conditions": value or []}
        elif key == "category":
            row.category = value.value if hasattr(value, "value") else value
        else:
            setattr(row, key, value)
    row.review_reasons = [*(row.review_reasons or []), "Edited by human reviewer"]



def list_evaluation_summaries(db: Session) -> list[dict]:
    """Lightweight rows for the dashboard (newest first)."""
    from sqlalchemy import func

    from app.models import Vendor

    counts = {(e, st): n for e, st, n in db.execute(
        select(Vendor.evaluation_id, Vendor.eligibility, func.count()).group_by(Vendor.evaluation_id, Vendor.eligibility))}
    out = []
    for ev in db.scalars(select(Evaluation).order_by(Evaluation.created_at.desc())):
        c = lambda st: counts.get((ev.id, st), 0)  # noqa: E731
        out.append({"id": ev.id, "name": ev.name, "workflow_status": ev.workflow_status, "criteria_status": ev.criteria_status,
                    "created_at": ev.created_at.isoformat(),
                    "vendors": sum(n for (e, _), n in counts.items() if e == ev.id),
                    "pass": c("PASS"), "fail": c("FAIL"), "pending": c("PENDING_HUMAN_REVIEW")})
    return out
