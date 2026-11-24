"""Text extraction with page-level provenance: PDF text layer first, OCR for pages without one."""

import hashlib
import re
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from app.document_processing.ocr import OcrEngine
from app.schemas.documents import PageText, ProcessedDocument

MIN_TEXT_CHARS = 25  # below this a PDF page is treated as scanned
OCR_RENDER_SCALE = 2.5  # ~180 dpi
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def normalize_text(text: str) -> str:
    text = _CONTROL.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def extract_document(path: Path, mime_type: str, ocr: OcrEngine | None) -> ProcessedDocument:
    """OCR engine is only needed (and only loaded by the caller) if a page lacks a text layer."""
    pages = _extract_pdf(path, ocr) if mime_type == "application/pdf" else _extract_image(path, ocr)
    flag = None
    if not any(p.text for p in pages):
        flag = "No readable text could be extracted (needs human attention)"
    return ProcessedDocument(
        filename=path.name, sha256=sha256_of(path), mime_type=mime_type,
        page_count=len(pages), pages=pages, flag=flag,
    )


def _extract_pdf(path: Path, ocr: OcrEngine | None) -> list[PageText]:
    pdf = pdfium.PdfDocument(str(path))
    pages: list[PageText] = []
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            text = normalize_text(page.get_textpage().get_text_range())
            source = "text_layer"
            if len(text) < MIN_TEXT_CHARS and ocr is not None:
                image = page.render(scale=OCR_RENDER_SCALE).to_pil()
                text, source = normalize_text(ocr.image_to_text(image)), "ocr"
            pages.append(PageText(page_number=index + 1, text=text, source=source))
    finally:
        pdf.close()
    return pages


def _extract_image(path: Path, ocr: OcrEngine | None) -> list[PageText]:
    text = ""
    if ocr is not None:
        with Image.open(path) as image:
            image.load()
            text = normalize_text(ocr.image_to_text(image))
    return [PageText(page_number=1, text=text, source="ocr")]
