"""Orchestrates intake of one vendor upload: validate -> (unzip) -> extract -> classify."""

import logging
from collections.abc import Callable
from pathlib import Path

from app.core.config import Settings
from app.document_processing.classifier import classify
from app.document_processing.extractor import extract_document, sha256_of
from app.document_processing.ocr import OcrEngine
from app.document_processing.upload_safety import safe_extract_zip, validate_upload
from app.schemas.documents import ProcessedDocument
from app.schemas.enums import DocumentClass


logger = logging.getLogger(__name__)


class DocumentIntake:
    def __init__(
        self,
        settings: Settings,
        ocr_factory: Callable[[], OcrEngine],
        category_patterns: dict[DocumentClass, list[str]] | None = None,
    ) -> None:
        self._settings = settings
        self._ocr_factory = ocr_factory  # lazy: OCR models load only if a page needs OCR
        self._patterns = category_patterns
        self._ocr: OcrEngine | None = None

    def _get_ocr(self) -> OcrEngine:
        if self._ocr is None:
            self._ocr = self._ocr_factory()
        return self._ocr

    def process_file(self, path: Path) -> list[ProcessedDocument]:
        """Process a stored file (PDF/image/ZIP). Every result is retained, even unknown ones."""
        with path.open("rb") as f:
            head = f.read(16)
        mime = validate_upload(path.name, head, path.stat().st_size, self._settings.max_upload_bytes)
        if mime == "application/zip":
            return self._process_zip(path)
        return [self._process_single(path, mime)]

    def _process_zip(self, path: Path) -> list[ProcessedDocument]:
        dest = path.parent / f"{path.stem}_unzipped"
        members = safe_extract_zip(
            path, dest,
            max_entries=self._settings.max_zip_entries,
            max_uncompressed_bytes=self._settings.max_zip_uncompressed_mb * 1024 * 1024,
            max_entry_bytes=self._settings.max_upload_bytes,
        )
        return [self._process_single(m, validate_upload(m.name, m.read_bytes()[:16], m.stat().st_size,
                                                        self._settings.max_upload_bytes)) for m in members]

    def _process_single(self, path: Path, mime: str) -> ProcessedDocument:
        try:
            doc = extract_document(path, mime, _LazyOcr(self._get_ocr))
        except Exception as exc:  # corrupt/encrypted file: keep it, flag it, never drop silently
            logger.warning("document extraction failed", extra={"file": path.name, "error": str(exc)})
            return ProcessedDocument(
                filename=path.name, sha256=sha256_of(path), mime_type=mime, page_count=0, pages=[],
                flag=f"Could not be processed ({type(exc).__name__}); needs human attention",
            )
        result = classify(doc, self._patterns)
        doc.document_class = result.document_class
        doc.classification_evidence = result.evidence
        doc.flag = doc.flag or result.flag
        return doc


class _LazyOcr:
    """Defers OCR engine construction until the first page actually needs OCR."""

    name = "lazy"

    def __init__(self, getter: Callable[[], OcrEngine]) -> None:
        self._getter = getter

    def image_to_text(self, image):  # noqa: ANN001
        return self._getter().image_to_text(image)
