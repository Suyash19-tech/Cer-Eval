from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requirement_code: str
    category: str
    description: str
    mandatory: bool
    certificate_name: str | None
    standard: str | None
    version: str | None
    validation_conditions: dict | None
    source_page: int | None
    supporting_text: str
    needs_human_review: bool
    review_reasons: list[str] | None
    confirmed: bool
    rejected: bool
    origin: str


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    workflow_status: str
    tender_sha256: str
    created_at: datetime
    requirements_confirmed_at: datetime | None
    requirements_confirmed_by: str | None
    error: str | None
    criteria_status: str = "NOT_STARTED"
    requirements: list[RequirementOut] = []
