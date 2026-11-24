"""Deterministic document classifier. Returns the class AND the evidence that triggered it.

X/Y/Z certification classes are tender-defined, so the caller passes `category_patterns`
(derived from the confirmed tender requirements: standard names, certificate names).
The LLM is not used here: classification must be reproducible and auditable. Ambiguous
documents end up as UNKNOWN and are flagged, never silently guessed.
"""

import re
from dataclasses import dataclass

from app.schemas.documents import ProcessedDocument
from app.schemas.enums import DocumentClass

_CERT = re.compile(r"\b(certificate|certification|certified|registration|accreditation|attestation)\b", re.I)
_COMMERCIAL = re.compile(
    r"\b(commercial (quotation|offer|bid)|unit price|total price|price schedule|gst|payment terms|"
    r"delivery terms|quoted price|taxes|incoterms)\b", re.I)
_TECHNICAL = re.compile(
    r"\b(technical (quotation|offer|proposal|compliance)|specification|datasheet|compliance statement|"
    r"deviation|technical parameters|make and model)\b", re.I)
_SUPPORTING = re.compile(r"\b(declaration|undertaking|company profile|annexure|brochure|letter of|power of attorney)\b", re.I)

CERT_CLASSES = (DocumentClass.X_CERTIFICATION, DocumentClass.Y_CERTIFICATION, DocumentClass.Z_CERTIFICATION)


@dataclass(frozen=True)
class Classification:
    document_class: DocumentClass
    evidence: str | None
    flag: str | None = None


def _snippet(match: re.Match[str], text: str) -> str:
    return text[max(0, match.start() - 40): match.end() + 40].replace("\n", " ").strip()


def classify(
    doc: ProcessedDocument, category_patterns: dict[DocumentClass, list[str]] | None = None
) -> Classification:
    text = "\n".join(p.text for p in doc.pages)
    head = f"{doc.filename}\n{text}"
    if not text.strip():
        return Classification(DocumentClass.UNKNOWN, None, "No readable text; retained for human review")

    cert_hit = _CERT.search(head)
    if cert_hit:
        matched: list[tuple[DocumentClass, str]] = []
        for cls, patterns in (category_patterns or {}).items():
            for pat in patterns:
                m = re.search(re.escape(pat), head, re.I)
                if m:
                    matched.append((cls, _snippet(m, head)))
                    break
        classes = {c for c, _ in matched}
        if len(classes) == 1:
            return Classification(matched[0][0], matched[0][1])
        if len(classes) > 1:  # genuinely ambiguous: do not guess
            return Classification(
                DocumentClass.OTHER_CERTIFICATION, _snippet(cert_hit, head),
                f"Matches several required certification classes: {sorted(c.value for c in classes)}",
            )
        return Classification(DocumentClass.OTHER_CERTIFICATION, _snippet(cert_hit, head))

    commercial = _COMMERCIAL.findall(head)
    technical = _TECHNICAL.findall(head)
    if len(commercial) >= 2 and len(commercial) > len(technical):
        return Classification(DocumentClass.COMMERCIAL_QUOTATION, f"{len(commercial)} commercial terms")
    if len(technical) >= 2 and len(technical) > len(commercial):
        return Classification(DocumentClass.TECHNICAL_QUOTATION, f"{len(technical)} technical terms")
    if (m := _SUPPORTING.search(head)):
        return Classification(DocumentClass.SUPPORTING_DOCUMENT, _snippet(m, head))
    return Classification(DocumentClass.UNKNOWN, None, "Could not classify; retained and flagged for review")
