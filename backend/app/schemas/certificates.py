from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import ValidationStatus


class LLMCertificate(BaseModel):
    holder_name: str | None = Field(default=None, description="Company the certificate was issued to, as written")
    certificate_number: str | None = None
    issuer: str | None = Field(default=None, description="Certification body, as written")
    supporting_text: str = Field(description="Exact verbatim sentence from the document stating the certified standard")
    expiry_text: str | None = Field(default=None, description="Exact verbatim text containing the expiry date")


class LLMCertificateList(BaseModel):
    certificates: list[LLMCertificate] = Field(default_factory=list, description="Empty if none is present")


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    requirement_code: str
    mandatory: bool
    status: ValidationStatus
    reasons: list[str] | None
    evidence: dict | None
    resolved_by: str | None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    document_class: str
    page_count: int | None
    needs_flag: str | None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    evaluation_id: str
    name: str
    eligibility: str | None
    eligibility_reason: str | None
    screening_status: str
    screening_error: str | None
    created_at: datetime
    documents: list[DocumentOut] = []
    findings: list[FindingOut] = []


class ReviewRequest(BaseModel):
    requirement_code: str
    decision: ValidationStatus
    reason: str = Field(min_length=10)
