"""Deterministic certificate validation. The LLM only proposes quotes; every status here is decided by Python.

Precedence for one candidate certificate: identity doubt (holder / evidence source) -> NEEDS_HUMAN_REVIEW,
then MISMATCH (wrong standard version), EXPIRED, insufficient remaining validity (MISMATCH), other doubt -> review.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.agents.tender_extractor import normalize
from app.schemas.enums import DocumentClass, ValidationStatus
from app.screening.dates import add_months, find_dates

CERT_CLASSES = {
    DocumentClass.X_CERTIFICATION.value, DocumentClass.Y_CERTIFICATION.value,
    DocumentClass.Z_CERTIFICATION.value, DocumentClass.OTHER_CERTIFICATION.value,
}
_LEGAL = {"ltd", "limited", "inc", "incorporated", "llc", "gmbh", "pvt", "private", "corp", "corporation", "co",
          "plc", "sa", "ag", "bv", "llp", "company", "the"}
_MONTHS_RE = re.compile(r"(\d+)\s*(?:\(\d+\)\s*)?months?", re.I)
_PLAIN_VALID = re.compile(r"^\s*(must be |shall be |to be )?(currently |presently )?valid( and (current|unexpired|in force))?"
                          r"( (on|at|as of|on or before) (the )?(bid|tender|submission)( due| closing)? date)?\s*\.?\s*$", re.I)


@dataclass
class RequirementSpec:
    code: str
    mandatory: bool
    standard: str | None
    version: str | None
    certificate_name: str | None
    conditions: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    document_id: str
    document_name: str
    document_category: str
    page_number: int
    supporting_text: str
    expiry_text: str | None
    holder_name: str | None
    certificate_number: str | None
    issuer: str | None
    grounded: bool  # supporting_text found verbatim in retrieved text


@dataclass
class Verdict:
    status: ValidationStatus
    reasons: list[str]
    evidence: dict | None = None


def squash(s: str) -> str:
    return re.sub(r"[\s:\-_/.]", "", s.lower())


def token_in(token: str, text: str) -> bool:
    return bool(token) and squash(token) in squash(text)


def required_token(spec: RequirementSpec) -> str | None:
    return spec.standard or spec.certificate_name


def cert_version(standard: str, quote: str) -> str | None:
    """Revision/year written right after the standard identifier in the quote, if any."""
    pat = r"\s*".join(re.escape(part) for part in re.findall(r"[A-Za-z]+|\d+", standard))
    m = re.search(pat, quote, re.I)
    if not m:
        return None
    tail = quote[m.end(): m.end() + 24]
    for rx in (r"^:\s*(\d{4})\b", r"^\s*[:\-]\s*(\d{4})\b", r"^([A-Z])\b", r"^\s*,?\s*Rev(?:ision)?\.?\s*([A-Z])\b",
               r"^\s*\(?(?:edition|ed\.?|version|v)?\s*(\d{4})\)?"):
        t = re.match(rx, tail, re.I if "Rev" in rx or "edition" in rx else 0)
        if t:
            return t.group(1)
    return None


def _name_key(name: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _LEGAL]
    return " ".join(words)


def holder_matches(holder: str, vendor_name: str) -> bool:
    h, v = _name_key(holder), _name_key(vendor_name)
    return bool(h and v and (h == v or h in v or v in h))


def min_remaining_months(conditions: list[str]) -> tuple[int | None, list[str]]:
    """(months required, conditions we could not interpret). Plain 'must be valid' is covered by the expiry check."""
    months: int | None = None
    unknown: list[str] = []
    for c in conditions:
        m = _MONTHS_RE.search(c)
        if m:
            months = max(months or 0, int(m.group(1)))
        elif not _PLAIN_VALID.match(c):
            unknown.append(c)
    return months, unknown


def validate_candidate(spec: RequirementSpec, cand: Candidate, *, vendor_name: str, as_of: date,
                       global_conditions: list[str]) -> Verdict:
    ev = {
        "document_id": cand.document_id, "document_name": cand.document_name, "page_number": cand.page_number,
        "supporting_text": cand.supporting_text, "expiry_text": cand.expiry_text, "holder_name": cand.holder_name,
        "certificate_number": cand.certificate_number, "issuer": cand.issuer, "expiry_date": None, "version_found": None,
    }
    doubt: list[str] = []
    identity: list[str] = []
    token = required_token(spec)

    if not cand.grounded:
        return Verdict(ValidationStatus.NEEDS_HUMAN_REVIEW, ["Quoted certificate text not found verbatim in vendor documents"], ev)
    if cand.document_category not in CERT_CLASSES:
        identity.append(f"Evidence comes from a non-certificate document ({cand.document_category})")
    if token and not token_in(token, cand.supporting_text):
        identity.append(f"Quoted text does not name the required standard/certificate '{token}'")
    if not cand.holder_name:
        identity.append("Certificate holder not identified")
    elif not holder_matches(cand.holder_name, vendor_name):
        identity.append(f"Certificate holder '{cand.holder_name}' does not match vendor '{vendor_name}'")
    if identity:
        return Verdict(ValidationStatus.NEEDS_HUMAN_REVIEW, identity, ev)

    # version
    if spec.standard and spec.version:
        found = cert_version(spec.standard, cand.supporting_text)
        ev["version_found"] = found
        if found is None:
            doubt.append(f"Could not read the version of {spec.standard} from the certificate (required {spec.version})")
        elif found.lower() != spec.version.lower():
            return Verdict(ValidationStatus.MISMATCH,
                           [f"Certificate is {spec.standard} {found}; tender requires {spec.version}"], ev)

    # expiry
    expiry: date | None = None
    if cand.expiry_text:
        dates, bad = find_dates(cand.expiry_text)
        if len(dates) == 1 and not bad:
            expiry = dates[0]
        else:
            doubt.append("Expiry date ambiguous or not parseable from the quoted text")
    else:
        doubt.append("No expiry date found on the certificate")
    if expiry:
        ev["expiry_date"] = expiry.isoformat()
        if expiry < as_of:
            return Verdict(ValidationStatus.EXPIRED, [f"Certificate expired on {expiry.isoformat()} (reference {as_of.isoformat()})"], ev)
        months, unknown = min_remaining_months(spec.conditions + global_conditions)
        if months and expiry < add_months(as_of, months):
            return Verdict(ValidationStatus.MISMATCH,
                           [f"Certificate expires {expiry.isoformat()}, less than the required {months} months after {as_of.isoformat()}"], ev)
        doubt.extend(f"Condition cannot be checked automatically: {u}" for u in unknown)
    if doubt:
        return Verdict(ValidationStatus.NEEDS_HUMAN_REVIEW, doubt, ev)
    return Verdict(ValidationStatus.COMPLIANT, ["All deterministic checks passed"], ev)


_RANK = {ValidationStatus.COMPLIANT: 0, ValidationStatus.NEEDS_HUMAN_REVIEW: 1, ValidationStatus.EXPIRED: 2,
         ValidationStatus.MISMATCH: 3, ValidationStatus.MISSING: 4}


def best_verdict(verdicts: list[Verdict]) -> Verdict:
    """If a vendor shows several certificates, the best one counts (e.g. renewed cert beats an old expired one)."""
    return min(verdicts, key=lambda v: _RANK[v.status])
