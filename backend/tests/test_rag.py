import hashlib
import re

import pytest

from app.rag.chunker import chunk_pages
from app.rag.service import RagService, VendorIsolationError
from app.rag.vector_store import FaissVectorStore
from app.schemas.documents import PageText, ProcessedDocument
from app.schemas.enums import DocumentClass

DIM = 256


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests (no model needed)."""

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
            out.append(v)
        return out


def doc(name, pages, cls=DocumentClass.X_CERTIFICATION):
    return ProcessedDocument(
        filename=name, sha256="0" * 64, mime_type="application/pdf", page_count=len(pages),
        pages=[PageText(page_number=i + 1, text=t, source="text_layer") for i, t in enumerate(pages)],
        document_class=cls, classification_evidence=None, flag=None,
    )


AS9100_A = "Certificate of Registration. Vendor A is certified to AS9100 Rev D for machining. Valid until 2027-05-01."
ISO_B = "Certificate of Registration. Vendor B is certified to ISO 14001:2015 environmental management."


def test_chunks_keep_page_and_metadata():
    long_page = "\n".join(f"Line number {i} of the certificate scope description text." for i in range(60))
    chunks = chunk_pages(document_id="d1", vendor_id="vA", document_name="x.pdf", document_category="X_CERTIFICATION",
                         pages=[PageText(page_number=1, text="short page text that is long enough", source="t"),
                                PageText(page_number=2, text=long_page, source="t")])
    assert {c.page_number for c in chunks} == {1, 2}
    assert len([c for c in chunks if c.page_number == 2]) > 1
    assert all(c.vendor_id == "vA" and c.document_name == "x.pdf" and len(c.text) <= 900 for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_chunker_requires_vendor():
    with pytest.raises(ValueError):
        chunk_pages(document_id="d", vendor_id="", document_name="x", document_category="c", pages=[])


def test_vendor_isolation_in_search():
    rag = RagService(HashEmbedder())
    rag.index_document("e1", "vA", "dA", doc("a.pdf", [AS9100_A]))
    rag.index_document("e1", "vB", "dB", doc("b.pdf", [ISO_B]))
    hits_a = rag.search("e1", "vA", "AS9100 certificate", k=5)
    assert hits_a and all(h.chunk.vendor_id == "vA" for h in hits_a)
    # Vendor B has no AS9100 text: searching B must never surface A's certificate
    hits_b = rag.search("e1", "vB", "AS9100 Rev D machining", k=5)
    assert all(h.chunk.vendor_id == "vB" and "AS9100" not in h.chunk.text for h in hits_b)


def test_evaluations_are_isolated_too():
    rag = RagService(HashEmbedder())
    rag.index_document("e1", "vA", "d1", doc("a.pdf", [AS9100_A]))
    assert rag.search("e2", "vA", "AS9100") == []


def test_category_filter_and_k():
    rag = RagService(HashEmbedder())
    rag.index_document("e1", "vA", "d1", doc("a.pdf", [AS9100_A], DocumentClass.X_CERTIFICATION))
    rag.index_document("e1", "vA", "d2", doc("q.pdf", ["Technical quotation: AS9100 machining capability statement."],
                                              DocumentClass.TECHNICAL_QUOTATION))
    hits = rag.search("e1", "vA", "AS9100", k=5, categories={"TECHNICAL_QUOTATION"})
    assert len(hits) == 1 and hits[0].chunk.document_name == "q.pdf"
    assert len(rag.search("e1", "vA", "AS9100", k=1)) == 1


def test_reindex_is_idempotent_and_removal_works():
    rag = RagService(HashEmbedder())
    rag.index_document("e1", "vA", "d1", doc("a.pdf", [AS9100_A]))
    rag.index_document("e1", "vA", "d1", doc("a.pdf", [AS9100_A]))
    assert len(rag.search("e1", "vA", "AS9100", k=10)) == 1
    assert rag.remove_document("e1", "vA", "d1") == 1
    assert rag.search("e1", "vA", "AS9100") == []


def test_persistence_roundtrip(tmp_path):
    rag = RagService(HashEmbedder(), root=tmp_path)
    rag.index_document("e1", "vA", "d1", doc("a.pdf", [AS9100_A]))
    fresh = RagService(HashEmbedder(), root=tmp_path)
    hits = fresh.search("e1", "vA", "AS9100 Rev D")
    assert hits and hits[0].chunk.page_number == 1 and hits[0].chunk.document_name == "a.pdf"
    assert fresh.search("e1", "vB", "AS9100") == []  # other vendor dir does not exist -> empty


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "a b", "x" * 100])
def test_ids_are_validated(bad):
    rag = RagService(HashEmbedder())
    with pytest.raises(ValueError):
        rag.search("e1", bad, "q")


def test_isolation_guard_trips_on_contaminated_store():
    class Leaky(FaissVectorStore):
        pass

    rag = RagService(HashEmbedder(), store_factory=lambda p: Leaky(p))
    rag.index_document("e1", "vA", "d1", doc("a.pdf", [AS9100_A]))
    # simulate a bug: another vendor's chunk lands in vA's store
    from dataclasses import replace
    store = rag._store("e1", "vA")
    foreign = replace(store._chunks[0], vendor_id="vB", chunk_id="evil")
    store.add([foreign], HashEmbedder().embed([foreign.text]))
    with pytest.raises(VendorIsolationError):
        rag.search("e1", "vA", "AS9100", k=5)


def test_empty_query_and_empty_store():
    rag = RagService(HashEmbedder())
    assert rag.search("e1", "vA", "anything") == []
    rag.index_document("e1", "vA", "d1", doc("a.pdf", [AS9100_A]))
    assert rag.search("e1", "vA", "   ") == []


# ---- default NumPy store behaves like the FAISS store ---------------------------------------------
from app.rag.vector_store import NumpyVectorStore, make_store  # noqa: E402


def test_default_store_is_numpy(monkeypatch):
    monkeypatch.delenv("HAL_VECTOR_STORE", raising=False)
    assert isinstance(make_store(None), NumpyVectorStore)
    monkeypatch.setenv("HAL_VECTOR_STORE", "faiss")
    assert isinstance(make_store(None), FaissVectorStore)


def test_numpy_and_faiss_stores_agree(tmp_path):
    docs = [("d1", AS9100_A), ("d2", ISO_B), ("d3", "Technical quotation: AS9100 machining capability statement.")]
    results = {}
    for name, factory in (("numpy", NumpyVectorStore), ("faiss", FaissVectorStore)):
        rag = RagService(HashEmbedder(), root=tmp_path / name, store_factory=lambda p, f=factory: f(p))
        for i, (d, t) in enumerate(docs):
            rag.index_document("e1", "vA", d, doc(f"{d}.pdf", [t]))
        results[name] = [(h.chunk.chunk_id, round(h.score, 4)) for h in rag.search("e1", "vA", "AS9100 certificate machining", k=3)]
        fresh = RagService(HashEmbedder(), root=tmp_path / name, store_factory=lambda p, f=factory: f(p))  # persistence
        assert [h.chunk.chunk_id for h in fresh.search("e1", "vA", "AS9100 certificate machining", k=3)] == [r[0] for r in results[name]]
    assert results["numpy"] == results["faiss"]


def test_numpy_store_rejects_dimension_mismatch_and_removes():
    s = NumpyVectorStore()
    from app.rag.chunker import Chunk
    c = lambda i, d: Chunk(f"c{i}", d, "vA", "x.pdf", 1, "X", "text " * 10)  # noqa: E731
    s.add([c(1, "d1"), c(2, "d2")], [[1, 0, 0], [0, 1, 0]])
    with pytest.raises(ValueError):
        s.add([c(3, "d3")], [[1, 0]])
    assert s.search([1, 0, 0], 1)[0][0].chunk_id == "c1"
    assert s.remove_document("d1") == 1 and s.search([1, 0, 0], 5)[0][0].chunk_id == "c2"
