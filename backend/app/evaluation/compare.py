"""Deterministic criterion comparison."""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.agents.tender_extractor import normalize
from app.evaluation.units import Quantity, convert, normalize_unit, parse_quantities


class CriterionStatus(StrEnum):
    MEETS = "MEETS"
    DEVIATES = "DEVIATES"
    MISSING_DETAIL = "MISSING_DETAIL"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class Comparator(StrEnum):
    GTE = "GTE"
    LTE = "LTE"
    EQ = "EQ"
    CONTAINS = "CONTAINS"


@dataclass
class Outcome:
    status: CriterionStatus
    reasons: list[str]
    vendor_value: float | None = None
    vendor_unit: str | None = None


_TOL = 1e-9


def pick_quantity(quote: str, unit: str | None) -> tuple[Quantity | None, str | None]:
    """Choose the number in the quote that answers the criterion; (None, reason) if absent or ambiguous."""
    qs = parse_quantities(quote)
    want = normalize_unit(unit)
    if want:
        cands = [q for q in qs if q.unit and convert(1.0, q.unit, want) is not None]
    else:
        cands = [q for q in qs if q.unit is None] or qs
    if not cands:
        return None, f"No value in unit '{unit}' found in the quoted text" if unit else "No number found in the quoted text"
    if len({(c.value, c.unit) for c in cands}) > 1:
        return None, "Several candidate values in the quoted text; cannot tell which one answers the criterion"
    return cands[0], None


def compare_numeric(comparator: Comparator, required: float, unit: str | None, quote: str) -> Outcome:
    q, why = pick_quantity(quote, unit)
    if q is None:
        return Outcome(CriterionStatus.NEEDS_HUMAN_REVIEW, [why or "Value not readable"])
    v = convert(q.value, q.unit, unit) if unit else q.value
    if v is None:
        return Outcome(CriterionStatus.NEEDS_HUMAN_REVIEW, [f"Cannot convert '{q.unit}' to '{unit}'"])
    ok = {Comparator.GTE: v >= required - _TOL, Comparator.LTE: v <= required + _TOL,
          Comparator.EQ: abs(v - required) <= max(_TOL, 1e-6 * abs(required))}[comparator]
    sym = {"GTE": ">=", "LTE": "<=", "EQ": "=="}[comparator.value]
    msg = f"Vendor {v:g}{' ' + unit if unit else ''} vs required {sym} {required:g}{' ' + unit if unit else ''}"
    return Outcome(CriterionStatus.MEETS if ok else CriterionStatus.DEVIATES, [msg], v, unit)


def compare_text(required_text: str, quote: str) -> Outcome:
    if not required_text.strip():
        return Outcome(CriterionStatus.NEEDS_HUMAN_REVIEW, ["Criterion has no required wording"])
    squash = lambda s: re.sub(r"[^a-z0-9]+", "", normalize(s))  # noqa: E731
    if squash(required_text) and squash(required_text) in squash(quote):
        return Outcome(CriterionStatus.MEETS, [f"Vendor text contains '{required_text}'"])
    return Outcome(CriterionStatus.NEEDS_HUMAN_REVIEW,
                   [f"Required wording '{required_text}' not found literally; semantic equivalence needs a human"])
