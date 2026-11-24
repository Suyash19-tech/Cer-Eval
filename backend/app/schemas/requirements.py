from enum import StrEnum

from pydantic import BaseModel, Field


class RequirementCategory(StrEnum):
    X = "X"
    Y = "Y"
    Z = "Z"
    OTHER_CERTIFICATION = "OTHER_CERTIFICATION"
    ELIGIBILITY_CONDITION = "ELIGIBILITY_CONDITION"


# ---- what the LLM is asked to produce (untrusted until verified) -----------------------------
class LLMRequirement(BaseModel):
    category: RequirementCategory = Field(
        description="X, Y or Z only if the tender itself labels the certification that way; "
        "OTHER_CERTIFICATION for other certifications; ELIGIBILITY_CONDITION for non-certificate conditions."
    )
    description: str
    mandatory: bool
    certificate_name: str | None = None
    standard: str | None = Field(default=None, description="e.g. 'AS9100' - only if written in the quote")
    version: str | None = Field(default=None, description="e.g. 'D' or '2015' - only if written in the quote")
    validation_conditions: list[str] = Field(default_factory=list)
    supporting_text: str = Field(description="Exact verbatim sentence(s) copied from the tender")
    unclear: bool = Field(default=False, description="True if the wording is ambiguous or contradictory")


class LLMRequirementList(BaseModel):
    requirements: list[LLMRequirement]


# ---- verified, persisted form -----------------------------------------------------------------
class ExtractedRequirement(BaseModel):
    requirement_id: str
    category: RequirementCategory
    description: str
    mandatory: bool
    certificate_name: str | None
    standard: str | None
    version: str | None
    validation_conditions: list[str]
    source_page: int | None
    supporting_text: str
    needs_human_review: bool
    review_reasons: list[str]


class RequirementEdit(BaseModel):
    description: str | None = None
    category: RequirementCategory | None = None
    mandatory: bool | None = None
    certificate_name: str | None = None
    standard: str | None = None
    version: str | None = None
    validation_conditions: list[str] | None = None


class RequirementDecision(BaseModel):
    requirement_id: str
    action: str = Field(pattern="^(accept|reject|edit)$")
    edits: RequirementEdit | None = None
    reason: str | None = None


class ManualRequirement(BaseModel):
    """Used when the extractor missed a requirement. The quote must exist in the tender text."""

    category: RequirementCategory
    description: str
    mandatory: bool = True
    certificate_name: str | None = None
    standard: str | None = None
    version: str | None = None
    validation_conditions: list[str] = Field(default_factory=list)
    supporting_text: str = Field(min_length=10)


class ConfirmRequirementsRequest(BaseModel):
    decisions: list[RequirementDecision] = Field(default_factory=list)
    additions: list[ManualRequirement] = Field(default_factory=list)
