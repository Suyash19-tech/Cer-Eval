"""Page-aware chunking. A chunk never spans pages, so its page number is always exact."""

import re
from dataclasses import dataclass

from app.schemas.documents import PageText

CHUNK_CHARS = 900
OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 20


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    vendor_id: str
    document_name: str
    page_number: int
    document_category: str
    text: str  # original text, unmodified apart from whitespace normalisation upstream


def _split_page(text: str, size: int, overlap: int) -> list[str]:
    """Split on paragraph/sentence boundaries into pieces <= size, with character overlap."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    units: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            units.append(para)
        else:  # long paragraph: split on sentences, hard-cut anything still too long
            for sent in re.split(r"(?<=[.!?;])\s+", para):
                while len(sent) > size:
                    units.append(sent[:size])
                    sent = sent[size:]
                if sent:
                    units.append(sent)
    chunks: list[str] = []
    cur = ""
    for unit in units:
        if cur and len(cur) + 1 + len(unit) > size:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = (tail.split(" ", 1)[-1] + " " + unit) if tail else unit  # start overlap at a word boundary
            if len(cur) > size:
                cur = unit
        else:
            cur = f"{cur}\n{unit}" if cur else unit
    if cur:
        chunks.append(cur)
    return chunks


def chunk_pages(
    *, document_id: str, vendor_id: str, document_name: str, document_category: str, pages: list[PageText],
    size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS,
) -> list[Chunk]:
    if not vendor_id:
        raise ValueError("vendor_id is required for every chunk")
    out: list[Chunk] = []
    for page in pages:
        for i, piece in enumerate(_split_page(page.text, size, overlap)):
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            out.append(Chunk(
                chunk_id=f"{document_id}:p{page.page_number}:c{i}", document_id=document_id, vendor_id=vendor_id,
                document_name=document_name, page_number=page.page_number, document_category=document_category,
                text=piece,
            ))
    return out
