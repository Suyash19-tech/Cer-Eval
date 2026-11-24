from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.compare import Comparator

COMMERCIAL_PARAMS = ("delivery_days", "payment_days", "validity_days", "total_price", "unit_price", "quantity")


class LLMCriterion(BaseModel):
    kind: Literal["TECHNICAL", "COMMERCIAL"]
    name: str = Field(description="Short name of the parameter, e.g. 'Operating pressure'")
    parameter: str | None = Field(default=None, description=f"Commercial only, one of {COMMERCIAL_PARAMS}, else null")
    comparator: Comparator
    required_value: float | None = Field(default=None, description="Number written in the sentence (for GTE/LTE/EQ)")
    required_text: str | None = Field(default=None, description="Wording that must appear (for CONTAINS)")
    unit: str | None = Field(default=None, description="Unit written in the sentence, e.g. 'bar', 'days'")
    mandatory: bool
    supporting_text: str = Field(description="Exact verbatim sentence from the tender")


class LLMCriterionList(BaseModel):
    criteria: list[LLMCriterion] = Field(default_factory=list)


class CriterionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    criterion_code: str
    kind: str
    name: str
    parameter: str | None
    comparator: str
    required_value: float | None
    required_text: str | None
    unit: str | None
    mandatory: bool
    weight: float
    source_page: int | None
    supporting_text: str
    needs_human_review: bool
    review_reasons: list[str] | None
    confirmed: bool
    rejected: bool


class CriterionEdit(BaseModel):
    name: str | None = None
    comparator: Comparator | None = None
    required_value: float | None = None
    required_text: str | None = None
    unit: str | None = None
    mandatory: bool | None = None
    weight: float | None = Field(default=None, ge=0)


class ManualCriterion(BaseModel):
    """A criterion a reviewer adds because extraction missed it. Must quote the tender verbatim."""

    kind: Literal["TECHNICAL", "COMMERCIAL"]
    name: str = Field(min_length=2, max_length=255)
    parameter: str | None = None
    comparator: Comparator
    required_value: float | None = None
    required_text: str | None = None
    unit: str | None = None
    mandatory: bool = True
    weight: float = Field(default=1.0, ge=0)
    supporting_text: str = Field(min_length=8, description="Exact sentence from the tender that states the requirement")
    reason: str = Field(min_length=10, description="Why extraction missed it")


class CriterionDecision(BaseModel):
    criterion_code: str
    action: Literal["accept", "reject", "edit"]
    reason: str | None = None
    edit: CriterionEdit | None = None


class ConfirmCriteriaRequest(BaseModel):
    decisions: list[CriterionDecision] = Field(default_factory=list)
    config: dict | None = None


class SpecProposal(BaseModel):
    supporting_text: str = Field(description="Exact verbatim sentence in the vendor document stating the value")


class SpecProposalList(BaseModel):
    values: list[SpecProposal] = Field(default_factory=list, description="Empty if the vendor does not state it")


class QuotedText(BaseModel):
    text: str = Field(description="Exact verbatim words copied from the quotation")


class LLMCommercial(BaseModel):
    total_price: QuotedText | None = None
    unit_price: QuotedText | None = None
    quantity: QuotedText | None = None
    taxes: QuotedText | None = None
    additional_charges: QuotedText | None = None
    delivery_terms: QuotedText | None = None
    payment_terms: QuotedText | None = None
    price_validity: QuotedText | None = None
