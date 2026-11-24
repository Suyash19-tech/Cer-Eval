"""Vector store abstraction. FAISS is the default implementation; the interface keeps it swappable."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import numpy as np

from app.rag.chunker import Chunk


class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def remove_document(self, document_id: str) -> int: ...
    def search(self, vector: list[float], k: int) -> list[tuple[Chunk, float]]: ...
    def save(self) -> None: ...
    def __len__(self) -> int: ...


class NumpyVectorStore:
    """Exact cosine search with NumPy (default). Same results as FAISS IndexFlatIP, no second OpenMP runtime.

    FAISS and PyTorch each bundle their own libomp; loading both in one process aborts ("OMP: Error #15") or can hang on
    macOS. The backend runs PyTorch (Granite embeddings, docTR OCR), so the default avoids FAISS. FAISS stays available
    (HAL_VECTOR_STORE=faiss) for deployments where the runtimes do not clash.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory
        self._chunks: list[Chunk] = []
        self._vecs = np.empty((0, 0), dtype="float32")
        if directory and (directory / "vectors.npy").is_file():
            self._vecs = np.load(directory / "vectors.npy")
            self._chunks = [Chunk(**c) for c in json.loads((directory / "chunks.json").read_text("utf-8"))]
            if len(self._vecs) != len(self._chunks):
                raise RuntimeError(f"Corrupt vector store at {directory}: vectors/metadata size mismatch")

    def __len__(self) -> int:
        return len(self._chunks)

    @staticmethod
    def _norm(a: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(a, axis=1, keepdims=True)
        return a / np.where(n == 0, 1, n)

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch")
        if not chunks:
            return
        arr = self._norm(np.asarray(vectors, dtype="float32"))
        if self._vecs.size and arr.shape[1] != self._vecs.shape[1]:
            raise ValueError(f"Embedding dimension {arr.shape[1]} does not match index dimension {self._vecs.shape[1]}")
        self._vecs = arr if not self._vecs.size else np.vstack([self._vecs, arr])
        self._chunks.extend(chunks)

    def remove_document(self, document_id: str) -> int:
        keep = [i for i, c in enumerate(self._chunks) if c.document_id != document_id]
        removed = len(self._chunks) - len(keep)
        if removed:
            self._vecs = self._vecs[keep] if keep else np.empty((0, 0), dtype="float32")
            self._chunks = [self._chunks[i] for i in keep]
        return removed

    def search(self, vector: list[float], k: int) -> list[tuple[Chunk, float]]:
        if not self._chunks or k <= 0:
            return []
        q = self._norm(np.asarray([vector], dtype="float32"))[0]
        scores = self._vecs @ q
        order = np.argsort(-scores, kind="stable")[: min(k, len(self._chunks))]
        return [(self._chunks[i], float(scores[i])) for i in order]

    def save(self) -> None:
        if self._dir is None or not self._chunks:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        np.save(self._dir / "vectors.npy", self._vecs)
        (self._dir / "chunks.json").write_text(json.dumps([asdict(c) for c in self._chunks]), "utf-8")


def make_store(path: Path | None) -> "VectorStore":
    import os

    return FaissVectorStore(path) if os.environ.get("HAL_VECTOR_STORE", "numpy").lower() == "faiss" else NumpyVectorStore(path)


class FaissVectorStore:
    """Exact inner-product search over L2-normalised vectors (= cosine). One instance per vendor."""

    def __init__(self, directory: Path | None = None, dim: int | None = None) -> None:
        import faiss

        self._faiss = faiss
        self._dir = directory
        self._chunks: list[Chunk] = []
        self._index = None
        self._dim = dim
        if directory and (directory / "index.faiss").is_file():
            self._index = faiss.read_index(str(directory / "index.faiss"))
            self._dim = self._index.d
            self._chunks = [Chunk(**c) for c in json.loads((directory / "chunks.json").read_text("utf-8"))]
            if self._index.ntotal != len(self._chunks):
                raise RuntimeError(f"Corrupt vector store at {directory}: index/metadata size mismatch")

    def __len__(self) -> int:
        return len(self._chunks)

    def _ensure(self, dim: int) -> None:
        if self._index is None:
            self._dim = dim
            self._index = self._faiss.IndexFlatIP(dim)
        elif dim != self._dim:
            raise ValueError(f"Embedding dimension {dim} does not match index dimension {self._dim}")

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch")
        if not chunks:
            return
        arr = np.asarray(vectors, dtype="float32")
        self._ensure(arr.shape[1])
        self._faiss.normalize_L2(arr)
        self._index.add(arr)
        self._chunks.extend(chunks)

    def remove_document(self, document_id: str) -> int:
        if self._index is None:
            return 0
        keep = [i for i, c in enumerate(self._chunks) if c.document_id != document_id]
        removed = len(self._chunks) - len(keep)
        if removed:
            vecs = self._index.reconstruct_n(0, self._index.ntotal)[keep] if keep else np.empty((0, self._dim), "float32")
            self._index = self._faiss.IndexFlatIP(self._dim)
            if len(keep):
                self._index.add(np.ascontiguousarray(vecs))
            self._chunks = [self._chunks[i] for i in keep]
        return removed

    def search(self, vector: list[float], k: int) -> list[tuple[Chunk, float]]:
        if self._index is None or not self._chunks or k <= 0:
            return []
        q = np.asarray([vector], dtype="float32")
        self._faiss.normalize_L2(q)
        scores, ids = self._index.search(q, min(k, len(self._chunks)))
        return [(self._chunks[i], float(s)) for s, i in zip(scores[0], ids[0]) if i >= 0]

    def save(self) -> None:
        if self._dir is None or self._index is None:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self._index, str(self._dir / "index.faiss"))
        (self._dir / "chunks.json").write_text(json.dumps([asdict(c) for c in self._chunks]), "utf-8")
