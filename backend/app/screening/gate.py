"""Hard eligibility gate. Pure function of mandatory findings; no LLM involvement."""

from app.schemas.enums import EligibilityStatus, ValidationStatus

HARD_FAIL = {ValidationStatus.MISSING, ValidationStatus.EXPIRED, ValidationStatus.MISMATCH}


def decide_eligibility(findings: list[tuple[str, bool, ValidationStatus]]) -> tuple[EligibilityStatus, str]:
    """findings: (requirement_code, mandatory, status). Non-mandatory findings never block a vendor."""
    mandatory = [(c, s) for c, m, s in findings if m]
    if not mandatory:
        return EligibilityStatus.PENDING_HUMAN_REVIEW, "No mandatory requirements were evaluated"
    failed = [f"{c}: {s.value}" for c, s in mandatory if s in HARD_FAIL]
    if failed:
        return EligibilityStatus.FAIL, "Mandatory requirement(s) not met: " + "; ".join(failed)
    pending = [c for c, s in mandatory if s == ValidationStatus.NEEDS_HUMAN_REVIEW]
    if pending:
        return EligibilityStatus.PENDING_HUMAN_REVIEW, "Awaiting human review of: " + ", ".join(pending)
    return EligibilityStatus.PASS, "All mandatory requirements compliant"
