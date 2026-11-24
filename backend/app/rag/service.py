"""Vendor-isolated retrieval.

Isolation rules (enforced structurally, then re-checked):
  * one physical index per (evaluation, vendor) - there is no shared index to filter;
  * every operation requires an explicit vendor_id; there is no "search all vendors" method;
  * every returned chunk is re-verified to carry the requested vendor_id.

Similarity scores are retrieval hints only. They are NEVER evidence that a certificate is valid or compliant;
downstream code must read the cited text and validate deterministically.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from app.rag.chunker import Chunk, chunk_pages
from app.rag.vector_store import VectorStore, make_store
from app.schemas.documents import ProcessedDocument

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float  # retrieval similarity only - not proof of anything


class VendorIsolationError(RuntimeError):
    pass


def _check_id(kind: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise ValueError(f"Invalid {kind}: {value!r}")
    return value


class RagService:
    def __init__(
        self, embedder: Embedder, root: Path | None = None,
        store_factory: Callable[[Path | None], VectorStore] = make_store,
        batch_size: int = 32,
    ) -> None:
        self._embedder = embedder
        self._root = root
        self._factory = store_factory
        self._batch = batch_size
        self._stores: dict[tuple[str, str], VectorStore] = {}

    def _store(self, evaluation_id: str, vendor_id: str) -> VectorStore:
        key = (_check_id("evaluation_id", evaluation_id), _check_id("vendor_id", vendor_id))
        if key not in self._stores:
            path = self._root / key[0] / key[1] if self._root else None
            self._stores[key] = self._factory(path)
        return self._stores[key]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            out.extend(self._embedder.embed(texts[i:i + self._batch]))
        return out

    def index_document(
        self, evaluation_id: str, vendor_id: str, document_id: str, doc: ProcessedDocument,
    ) -> int:
        """(Re)index one document into that vendor's index. Idempotent per document_id."""
        _check_id("document_id", document_id)
        store = self._store(evaluation_id, vendor_id)
        chunks = chunk_pages(
            document_id=document_id, vendor_id=vendor_id, document_name=doc.filename,
            document_category=doc.document_class.value, pages=doc.pages,
        )
        vectors = self._embed([c.text for c in chunks])  # embed first: a failure leaves the old index intact
        store.remove_document(document_id)
        store.add(chunks, vectors)
        store.save()
        return len(chunks)

    def remove_document(self, evaluation_id: str, vendor_id: str, document_id: str) -> int:
        store = self._store(evaluation_id, vendor_id)
        n = store.remove_document(document_id)
        store.save()
        return n

    def search(
        self, evaluation_id: str, vendor_id: str, query: str, k: int = 5,
        categories: set[str] | None = None, min_score: float | None = None,
    ) -> list[SearchHit]:
        store = self._store(evaluation_id, vendor_id)
        if not query.strip():
            return []
        qvec = self._embed([query])[0]
        # over-fetch when category-filtering so the filter cannot starve the result list
        raw = store.search(qvec, len(store) if categories else k)
        hits: list[SearchHit] = []
        for chunk, score in raw:
            if chunk.vendor_id != vendor_id:  # defence in depth; should be unreachable
                raise VendorIsolationError(f"Chunk of vendor {chunk.vendor_id} surfaced in vendor {vendor_id} search")
            if categories and chunk.document_category not in categories:
                continue
            if min_score is not None and score < min_score:
                continue
            hits.append(SearchHit(chunk, score))
            if len(hits) >= k:
                break
        return hits
