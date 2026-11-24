"""Vendor intake, certificate screening, human review. Statuses are set here by deterministic code only."""

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.certificate_extractor import locate, propose_certificates
from app.agents.tender_extractor import StructuredLLM
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.document_processing.service import DocumentIntake
from app.document_processing.upload_safety import sanitize_filename
from app.models import CertificateFinding, Document, Evaluation, ReviewDecision, TenderRequirement, Vendor
from app.rag.service import RagService
from app.schemas.enums import EligibilityStatus, ValidationStatus, WorkflowStatus
from app.schemas.requirements import RequirementCategory
from app.screening.gate import decide_eligibility
from app.screening.validator import (
    Candidate, RequirementSpec, Verdict, best_verdict, min_remaining_months, required_token, token_in, validate_candidate,
)
from app.services.tender_service import audit, get_evaluation

logger = logging.getLogger(__name__)
TOP_K = 6


def get_vendor(db: Session, evaluation_id: str, vendor_id: str) -> Vendor:
    v = db.get(Vendor, vendor_id)
    if v is None or v.evaluation_id != evaluation_id:
        raise NotFoundError("Vendor not found")
    return v


def create_vendor(
    db: Session, settings: Settings, rag: RagService, intake: DocumentIntake, evaluation_id: str, name: str,
    files: list[tuple[str, bytes]],
) -> Vendor:
    ev = get_evaluation(db, evaluation_id)
    if ev.workflow_status not in (WorkflowStatus.REQUIREMENTS_CONFIRMED.value, WorkflowStatus.RUNNING.value):
        raise ConflictError("Tender requirements must be confirmed before vendors are added")
    if not name.strip():
        raise ValidationFailedError("Vendor name is required")
    if not files:
        raise ValidationFailedError("At least one document is required")
    vendor = Vendor(evaluation_id=evaluation_id, name=name.strip())
    db.add(vendor)
    db.flush()
    vdir = settings.uploads_dir / evaluation_id / vendor.id
    vdir.mkdir(parents=True, exist_ok=True)
    for raw_name, content in files:
        if len(content) > settings.max_upload_bytes:
            raise ValidationFailedError(f"{raw_name}: exceeds {settings.max_upload_mb} MB")
        path = vdir / sanitize_filename(raw_name)
        if path.exists():
            path = vdir / f"{len(list(vdir.iterdir()))}_{path.name}"
        path.write_bytes(content)
        for doc in intake.process_file(path):  # raises ValidationFailedError for bad types / unsafe ZIPs
            row = Document(
                evaluation_id=evaluation_id, vendor_id=vendor.id, filename=doc.filename, stored_path=str(path),
                sha256=doc.sha256, mime_type=doc.mime_type, page_count=doc.page_count,
                document_class=doc.document_class.value, needs_flag=doc.flag,
                pages=[p.model_dump() for p in doc.pages],
            )
            db.add(row)
            db.flush()
            rag.index_document(evaluation_id, vendor.id, row.id, doc)
    ev.workflow_status = WorkflowStatus.RUNNING.value
    audit(db, "system", "vendor.created", evaluation_id, {"vendor_id": vendor.id, "documents": len(files)})
    db.flush()
    return vendor


def _spec(r: TenderRequirement) -> RequirementSpec:
    conds = (r.validation_conditions or {}).get("conditions", [])
    return RequirementSpec(r.requirement_code, r.mandatory, r.standard, r.version, r.certificate_name, list(conds))


def _vendor_pages_text(db: Session, vendor_id: str) -> list[str]:
    docs = db.scalars(select(Document).where(Document.vendor_id == vendor_id)).all()
    return [p["text"] for d in docs for p in (d.pages or [])]


def screen_requirement(
    spec: RequirementSpec, *, vendor: Vendor, all_text: list[str], rag: RagService, llm: StructuredLLM,
    as_of: date, global_conditions: list[str],
) -> Verdict:
    token = required_token(spec)
    if not token:
        return Verdict(ValidationStatus.NEEDS_HUMAN_REVIEW, ["Requirement has no standard or certificate name to search for"])
    # Deterministic MISSING: the required standard is not mentioned anywhere in this vendor's documents.
    if not any(token_in(token, t) for t in all_text):
        return Verdict(ValidationStatus.MISSING, [f"No document from this vendor mentions '{token}'"])
    label = " ".join(x for x in (spec.certificate_name, spec.standard, spec.version) if x)
    hits = rag.search(vendor.evaluation_id, vendor.id, f"{label} certificate", k=TOP_K)
    proposals = propose_certificates(llm, label, hits)
    if not proposals:
        return Verdict(ValidationStatus.NEEDS_HUMAN_REVIEW,
                       [f"'{token}' is mentioned in the documents but no certificate was identified"])
    verdicts = []
    for p in proposals:
        hit = locate(p.supporting_text, hits)
        expiry_ok = bool(p.expiry_text) and locate(p.expiry_text, hits) is not None
        holder_ok = bool(p.holder_name) and locate(p.holder_name, hits) is not None
        c = hit.chunk if hit else None
        cand = Candidate(
            document_id=c.document_id if c else "", document_name=c.document_name if c else "",
            document_category=c.document_category if c else "", page_number=c.page_number if c else 0,
            supporting_text=p.supporting_text, expiry_text=p.expiry_text if expiry_ok else None,
            holder_name=p.holder_name if holder_ok else None, certificate_number=p.certificate_number,
            issuer=p.issuer, grounded=hit is not None,
        )
        v = validate_candidate(spec, cand, vendor_name=vendor.name, as_of=as_of, global_conditions=global_conditions)
        if p.expiry_text and not expiry_ok and v.status == ValidationStatus.NEEDS_HUMAN_REVIEW:
            v.reasons.append("Expiry text proposed by the model was not found verbatim in the documents")
        verdicts.append(v)
    return best_verdict(verdicts)


def recompute_eligibility(db: Session, vendor: Vendor) -> None:
    rows = db.scalars(select(CertificateFinding).where(CertificateFinding.vendor_id == vendor.id)).all()
    status, reason = decide_eligibility([(r.requirement_code, r.mandatory, ValidationStatus(r.status)) for r in rows])
    vendor.eligibility, vendor.eligibility_reason = status.value, reason


def screen_vendor(
    session_factory: Callable[[], Session], llm: StructuredLLM, rag: RagService, evaluation_id: str, vendor_id: str,
    as_of: date | None = None,
) -> None:
    as_of = as_of or date.today()
    db = session_factory()
    try:
        vendor = get_vendor(db, evaluation_id, vendor_id)
        vendor.screening_status, vendor.screening_error = "SCREENING", None
        db.commit()
        reqs = db.scalars(select(TenderRequirement).where(
            TenderRequirement.evaluation_id == evaluation_id, TenderRequirement.confirmed.is_(True),
            TenderRequirement.rejected.is_(False)).order_by(TenderRequirement.requirement_code)).all()
        eligibility_reqs = [r for r in reqs if r.category == RequirementCategory.ELIGIBILITY_CONDITION.value]
        cert_reqs = [r for r in reqs if r.category != RequirementCategory.ELIGIBILITY_CONDITION.value]
        # tender-wide validity rules ("at least 6 months remaining") apply to every certificate
        global_conditions = [r.description for r in eligibility_reqs if min_remaining_months([r.description])[0]]
        other_elig = [r for r in eligibility_reqs if not min_remaining_months([r.description])[0]]
        all_text = _vendor_pages_text(db, vendor_id)
        computed = [(r, screen_requirement(_spec(r), vendor=vendor, all_text=all_text, rag=rag, llm=llm, as_of=as_of,
                                           global_conditions=global_conditions)) for r in cert_reqs]  # inference first
        db.execute(delete(CertificateFinding).where(CertificateFinding.vendor_id == vendor_id))  # then one short write
        for r, verdict in computed:
            db.add(CertificateFinding(evaluation_id=evaluation_id, vendor_id=vendor_id, requirement_code=r.requirement_code,
                                      mandatory=r.mandatory, status=verdict.status.value, reasons=verdict.reasons,
                                      evidence=verdict.evidence))
        for r in other_elig:  # not machine-checkable: a human must verify, never silently skipped
            db.add(CertificateFinding(evaluation_id=evaluation_id, vendor_id=vendor_id, requirement_code=r.requirement_code,
                                      mandatory=r.mandatory, status=ValidationStatus.NEEDS_HUMAN_REVIEW.value,
                                      reasons=["Eligibility condition requires manual verification: " + r.description],
                                      evidence=None))
        db.flush()
        recompute_eligibility(db, vendor)
        vendor.screening_status = "DONE"
        audit(db, "system", "vendor.screened", evaluation_id, {"vendor_id": vendor_id, "eligibility": vendor.eligibility})
        db.commit()
    except Exception as exc:  # never leave a vendor looking screened or eligible after a failure
        logger.exception("screening failed")
        db.rollback()
        v = db.get(Vendor, vendor_id)
        if v:
            v.screening_status, v.screening_error = "FAILED", f"{type(exc).__name__}: {exc}"[:500]
            v.eligibility, v.eligibility_reason = None, None
            db.commit()
    finally:
        db.close()


def review_finding(db: Session, evaluation_id: str, vendor_id: str, reviewer_id: str, requirement_code: str,
                   decision: ValidationStatus, reason: str) -> Vendor:
    vendor = get_vendor(db, evaluation_id, vendor_id)
    if decision == ValidationStatus.NEEDS_HUMAN_REVIEW:
        raise ValidationFailedError("A review decision must resolve the finding")
    row = db.scalars(select(CertificateFinding).where(
        CertificateFinding.vendor_id == vendor_id, CertificateFinding.requirement_code == requirement_code)).first()
    if row is None:
        raise NotFoundError("Finding not found")
    if row.status != ValidationStatus.NEEDS_HUMAN_REVIEW.value:
        raise ConflictError("Only findings awaiting human review can be resolved")
    db.add(ReviewDecision(evaluation_id=evaluation_id, vendor_id=vendor_id, requirement_code=requirement_code,
                          decision=decision.value, reviewer_id=reviewer_id, reason=reason,
                          evidence=str((row.evidence or {}).get("supporting_text")), previous_status=row.status,
                          new_status=decision.value))
    row.status, row.resolved_by = decision.value, reviewer_id
    db.flush()
    recompute_eligibility(db, vendor)
    audit(db, reviewer_id, "finding.reviewed", evaluation_id,
          {"vendor_id": vendor_id, "requirement": requirement_code, "decision": decision.value})
    db.flush()
    return vendor


def list_findings(db: Session, vendor_id: str) -> list[CertificateFinding]:
    return list(db.scalars(select(CertificateFinding).where(CertificateFinding.vendor_id == vendor_id)
                           .order_by(CertificateFinding.requirement_code)))


def list_vendors(db: Session, evaluation_id: str) -> list[Vendor]:
    get_evaluation(db, evaluation_id)
    return list(db.scalars(select(Vendor).where(Vendor.evaluation_id == evaluation_id).order_by(Vendor.name)))


def document_file(db: Session, settings: Settings, evaluation_id: str, vendor_id: str, document_id: str) -> tuple[Path, str, str]:
    """(path, mime, download name) of an original document. Never serves anything outside this vendor's upload folder."""
    get_vendor(db, evaluation_id, vendor_id)
    doc = db.get(Document, document_id)
    if doc is None or doc.vendor_id != vendor_id:
        raise NotFoundError("Document not found")
    stored = Path(doc.stored_path)
    path = stored
    if stored.suffix.lower() == ".zip":  # member of an extracted archive
        root = stored.parent / f"{stored.stem}_unzipped"
        matches = [m for m in root.rglob(Path(doc.filename).name) if m.is_file()] if root.is_dir() else []
        if len(matches) != 1:
            raise NotFoundError("Original file not available")
        path = matches[0]
    base = (settings.uploads_dir / evaluation_id / vendor_id).resolve()
    resolved = path.resolve()
    if not resolved.is_file() or base not in resolved.parents:
        raise NotFoundError("Original file not available")
    return resolved, doc.mime_type, sanitize_filename(doc.filename)
