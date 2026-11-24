"""Tender requirement extraction: LLM proposes, deterministic verification disposes.

Every LLM requirement must carry a verbatim quote. We locate the quote in the page text (that gives
the authoritative source page). Anything we cannot ground is NOT trusted: unsupported standard/version
values are nulled and the requirement is flagged for human review. Nothing is ever auto-confirmed.
"""

import logging
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.schemas.documents import PageText
from app.schemas.requirements import (
    ExtractedRequirement, LLMRequirement, LLMRequirementList, ManualRequirement, RequirementCategory,
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

WINDOW_CHARS = 5000
MIN_QUOTE_CHARS = 15
_ID_PREFIX = {
    RequirementCategory.X: "X", RequirementCategory.Y: "Y", RequirementCategory.Z: "Z",
    RequirementCategory.OTHER_CERTIFICATION: "OTH", RequirementCategory.ELIGIBILITY_CONDITION: "ELIG",
}

INSTRUCTION = """Extract every vendor certification requirement and every tender-specific vendor eligibility condition
from the tender text. Return one item per requirement.

Rules:
- supporting_text: copy the exact sentence from the tender, never paraphrase.
- category: X, Y or Z only when the tender itself labels the certification that way ("Category X", etc.);
  OTHER_CERTIFICATION for any other certification; ELIGIBILITY_CONDITION for general conditions that are not a
  specific certificate (issuer accreditation, minimum remaining validity, scope wording).
- certificate_name and standard MUST be filled whenever the sentence names a certificate or standard.
  Put the standard identifier alone in standard (e.g. "AS9100", "ISO 14001", "NADCAP") and the revision or year
  alone in version (e.g. "D", "2015"). Use null only when the sentence truly does not contain them.
- mandatory=true if the sentence says shall / must / mandatory / required; false if desirable / optional / may.
- validation_conditions: list conditions stated in the sentence (e.g. "valid on the bid due date").
- unclear=true only if the sentence is ambiguous. Never invent requirements.

Example sentence: "2.1 Category X: The vendor shall hold a valid AS9100 Rev D certificate for machining."
Example item: {"category":"X","description":"Valid AS9100 Rev D certificate for machining","mandatory":true,
"certificate_name":"AS9100 Rev D","standard":"AS9100","version":"D","validation_conditions":["must be valid"],
"supporting_text":"2.1 Category X: The vendor shall hold a valid AS9100 Rev D certificate for machining.","unclear":false}"""


class StructuredLLM(Protocol):
    def extract(self, schema: type[T], instruction: str, document_text: str, max_tokens: int = 1024) -> T: ...


def normalize(s: str) -> str:
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def find_quote_page(quote: str, pages: list[PageText]) -> int | None:
    """Page number whose normalised text contains the normalised quote, else None."""
    needle = normalize(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    for page in pages:
        if needle in normalize(page.text):
            return page.page_number
    return None


_REQUIRED_WORDS = re.compile(r"\b(shall|must|mandatory|required|essential)\b", re.I)
_OPTIONAL_WORDS = re.compile(r"\b(desirable|optional|preferred|may)\b|not mandatory", re.I)


def implied_mandatory(quote: str) -> bool | None:
    """What the tender wording implies, or None if it has no modal word. Optional wording wins."""
    if _OPTIONAL_WORDS.search(quote):
        return False
    return True if _REQUIRED_WORDS.search(quote) else None


_STD_PATTERNS = (
    re.compile(r"\b(AS) ?(\d{4})([A-Z])?\b"),
    re.compile(r"\b(ISO(?:/IEC)?) ?(\d{4,5})(?::(\d{4}))?"),
    re.compile(r"\b(EN) ?(\d{4,5})(?::(\d{4}))?"),
    re.compile(r"\b(NADCAP)\b", re.I),
)
_REV = re.compile(r"\bRev(?:ision)?\.? ?([A-Z])\b")


def derive_standard(quote: str) -> tuple[str | None, str | None]:
    """Deterministic fallback: (standard, version) read straight from the quote, only if unambiguous."""
    found: dict[str, str | None] = {}
    for pat in _STD_PATTERNS:
        for m in pat.finditer(quote):
            if pat is _STD_PATTERNS[3]:
                found["NADCAP"] = None
            else:
                sep = "" if m.group(1) == "AS" else " "  # tenders write AS9100 but ISO 14001
                found[f"{m.group(1)}{sep}{m.group(2)}"] = m.group(3)
    if len(found) != 1:
        return None, None
    (std, ver), = found.items()
    if ver is None and (rev := _REV.search(quote)):
        ver = rev.group(1)
    return std, ver


def _contains_token(token: str, quote: str) -> bool:
    squash = lambda x: re.sub(r"[\s:\-_]", "", x.lower())  # noqa: E731
    return squash(token) in squash(quote)


def make_windows(pages: list[PageText], limit: int = WINDOW_CHARS) -> list[str]:
    windows, current, size = [], [], 0
    for page in pages:
        block = f"[[PAGE {page.page_number}]]\n{page.text}"
        if current and size + len(block) > limit:
            windows.append("\n\n".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block)
    if current:
        windows.append("\n\n".join(current))
    return windows


def verify(req: LLMRequirement | ManualRequirement, pages: list[PageText]) -> tuple[ExtractedRequirement, bool]:
    """Return (requirement with provisional id '', ok_flag). IDs are assigned later."""
    reasons: list[str] = []
    page = find_quote_page(req.supporting_text, pages)
    if page is None:
        reasons.append("Supporting text not found verbatim in tender; possible hallucination")
    standard, version = req.standard, req.version
    if standard and not _contains_token(standard, req.supporting_text):
        reasons.append(f"Standard '{standard}' not present in supporting text; removed")
        standard = None
    if version and not _contains_token(version, req.supporting_text):
        reasons.append(f"Version '{version}' not present in supporting text; removed")
        version = None
    if standard is None and req.category != RequirementCategory.ELIGIBILITY_CONDITION:
        standard, derived_version = derive_standard(req.supporting_text)
        version = version or derived_version
    implied = implied_mandatory(req.supporting_text)
    if implied is not None and implied != req.mandatory:
        reasons.append(f"Mandatory flag ({req.mandatory}) contradicts the tender wording")
    if getattr(req, "unclear", False):
        reasons.append("Extractor marked the wording as unclear")
    is_cert = req.category != RequirementCategory.ELIGIBILITY_CONDITION
    if is_cert and not (req.certificate_name or standard):
        reasons.append("Certification requirement without certificate name or standard")
    out = ExtractedRequirement(
        requirement_id="", category=req.category, description=req.description, mandatory=req.mandatory,
        certificate_name=req.certificate_name, standard=standard, version=version,
        validation_conditions=req.validation_conditions, source_page=page,
        supporting_text=req.supporting_text, needs_human_review=bool(reasons), review_reasons=reasons,
    )
    return out, not reasons


def assign_ids(reqs: list[ExtractedRequirement], existing: dict[str, int] | None = None) -> None:
    counters = dict(existing or {})
    for r in reqs:
        prefix = _ID_PREFIX[r.category]
        counters[prefix] = counters.get(prefix, 0) + 1
        r.requirement_id = f"REQ-{prefix}-{counters[prefix]:03d}"


class TenderRequirementExtractor:
    def __init__(self, llm: StructuredLLM) -> None:
        self._llm = llm

    def extract(self, pages: list[PageText]) -> list[ExtractedRequirement]:
        seen: set[str] = set()
        out: list[ExtractedRequirement] = []
        for window in make_windows(pages):
            try:
                result = self._llm.extract(LLMRequirementList, INSTRUCTION, window, max_tokens=2048)
            except Exception:  # malformed/truncated model output must not lose the whole tender
                logger.exception("tender window extraction failed")
                raise
            for raw in result.requirements:
                key = normalize(raw.supporting_text)
                if key in seen:
                    continue
                seen.add(key)
                out.append(verify(raw, pages)[0])
        assign_ids(out)
        return out
