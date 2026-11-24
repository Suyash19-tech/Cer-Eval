"""Persistent entities. Every vendor-owned row carries evaluation_id + vendor_id (isolation)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.schemas.enums import DocumentClass, EligibilityStatus, WorkflowStatus


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    tender_path: Mapped[str] = mapped_column(String(1024))
    tender_sha256: Mapped[str] = mapped_column(String(64))
    workflow_status: Mapped[str] = mapped_column(String(48), default=WorkflowStatus.CREATED.value)
    requirements_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requirements_confirmed_by: Mapped[str | None] = mapped_column(String(128))
    tender_pages: Mapped[list | None] = mapped_column(JSON)  # [{page_number, text, source}]
    error: Mapped[str | None] = mapped_column(Text)
    evaluation_config: Mapped[dict | None] = mapped_column(JSON)  # see app/evaluation/config.py
    criteria_status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED")  # NOT_STARTED|EXTRACTING|PENDING_CONFIRMATION|CONFIRMED|FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    vendors: Mapped[list["Vendor"]] = relationship(back_populates="evaluation", cascade="all, delete-orphan")
    requirements: Mapped[list["TenderRequirement"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    eligibility: Mapped[str | None] = mapped_column(String(32), default=None)  # EligibilityStatus
    eligibility_reason: Mapped[str | None] = mapped_column(Text)
    screening_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED")  # NOT_STARTED|SCREENING|DONE|FAILED
    screening_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    evaluation: Mapped[Evaluation] = relationship(back_populates="vendors")
    documents: Mapped[list["Document"]] = relationship(back_populates="vendor", cascade="all, delete-orphan")


class Document(Base):
    """A document belongs to exactly one vendor (vendor_id is NOT NULL)."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(128))
    page_count: Mapped[int | None] = mapped_column(Integer)
    document_class: Mapped[str] = mapped_column(String(48), default=DocumentClass.UNKNOWN.value)
    needs_flag: Mapped[str | None] = mapped_column(Text)  # e.g. unknown document warning
    pages: Mapped[list | None] = mapped_column(JSON)  # [{page_number, text, source}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    vendor: Mapped[Vendor] = relationship(back_populates="documents")


class TenderRequirement(Base):
    __tablename__ = "tender_requirements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    requirement_code: Mapped[str] = mapped_column(String(64))  # e.g. REQ-X-001
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    mandatory: Mapped[bool] = mapped_column(default=True)
    certificate_name: Mapped[str | None] = mapped_column(String(255))
    standard: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(64))
    validation_conditions: Mapped[dict | None] = mapped_column(JSON)
    source_page: Mapped[int | None] = mapped_column(Integer)
    supporting_text: Mapped[str] = mapped_column(Text)
    needs_human_review: Mapped[bool] = mapped_column(default=False)
    review_reasons: Mapped[list | None] = mapped_column(JSON)
    confirmed: Mapped[bool] = mapped_column(default=False)
    rejected: Mapped[bool] = mapped_column(default=False)
    origin: Mapped[str] = mapped_column(String(16), default="LLM")  # LLM | MANUAL

    evaluation: Mapped[Evaluation] = relationship(back_populates="requirements")


class EvaluationCriterion(Base):
    """A tender technical or commercial criterion. Proposed by the LLM (grounded), confirmed by a human."""

    __tablename__ = "evaluation_criteria"
    __table_args__ = (UniqueConstraint("evaluation_id", "criterion_code"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    criterion_code: Mapped[str] = mapped_column(String(32))  # TECH-001 / COM-001
    kind: Mapped[str] = mapped_column(String(16))  # TECHNICAL | COMMERCIAL
    name: Mapped[str] = mapped_column(String(255))
    parameter: Mapped[str | None] = mapped_column(String(64))  # known commercial field, else None
    comparator: Mapped[str] = mapped_column(String(16))  # GTE | LTE | EQ | CONTAINS
    required_value: Mapped[float | None] = mapped_column()
    required_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))
    mandatory: Mapped[bool] = mapped_column(default=True)
    weight: Mapped[float] = mapped_column(default=1.0)
    source_page: Mapped[int | None] = mapped_column(Integer)
    supporting_text: Mapped[str] = mapped_column(Text)
    needs_human_review: Mapped[bool] = mapped_column(default=False)
    review_reasons: Mapped[list | None] = mapped_column(JSON)
    confirmed: Mapped[bool] = mapped_column(default=False)
    rejected: Mapped[bool] = mapped_column(default=False)
    origin: Mapped[str] = mapped_column(String(16), default="LLM")


class CriterionFinding(Base):
    """One (vendor, criterion) comparison. Status is set by Python only."""

    __tablename__ = "criterion_findings"
    __table_args__ = (UniqueConstraint("vendor_id", "criterion_code"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    criterion_code: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    mandatory: Mapped[bool] = mapped_column(default=True)
    weight: Mapped[float] = mapped_column(default=1.0)
    status: Mapped[str] = mapped_column(String(24))  # CriterionStatus
    reasons: Mapped[list | None] = mapped_column(JSON)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    resolved_by: Mapped[str | None] = mapped_column(String(128))


class CommercialSummary(Base):
    """Extracted, verified commercial terms of one vendor (null = not provided; never invented)."""

    __tablename__ = "commercial_summaries"

    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    needs_human_review: Mapped[bool] = mapped_column(default=False)
    review_reasons: Mapped[list | None] = mapped_column(JSON)


class CertificateFinding(Base):
    """One row of the compliance matrix: (vendor, requirement) -> status + evidence. Status is set by Python only."""

    __tablename__ = "certificate_findings"
    __table_args__ = (UniqueConstraint("vendor_id", "requirement_code"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    requirement_code: Mapped[str] = mapped_column(String(64))
    mandatory: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(32))  # ValidationStatus
    reasons: Mapped[list | None] = mapped_column(JSON)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    resolved_by: Mapped[str | None] = mapped_column(String(128))  # set when a human resolved it
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ReviewDecision(Base):
    """Immutable audit record of a human resolution of a pending requirement."""

    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    requirement_code: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(32))
    reviewer_id: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    previous_status: Mapped[str] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    evaluation_id: Mapped[str | None] = mapped_column(String(32), index=True)
    detail: Mapped[dict | None] = mapped_column(JSON)


# Re-exported for type clarity; EligibilityStatus is stored as a string column on Vendor.
__all__ = [
    "AuditLog", "CertificateFinding", "CommercialSummary", "CriterionFinding", "Document", "EvaluationCriterion", "EligibilityStatus", "Evaluation", "ReviewDecision", "TenderRequirement", "Vendor",
]
