from pydantic import BaseModel

from app.schemas.enums import DocumentClass


class PageText(BaseModel):
    page_number: int  # 1-based
    text: str
    source: str  # "text_layer" | "ocr"


class ProcessedDocument(BaseModel):
    filename: str
    sha256: str
    mime_type: str
    page_count: int
    pages: list[PageText]
    document_class: DocumentClass = DocumentClass.UNKNOWN
    classification_evidence: str | None = None
    flag: str | None = None  # e.g. unknown / no-readable-text warnings
