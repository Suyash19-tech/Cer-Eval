"""Opt-in: real Granite embedding model. HAL_RUN_LLM_TESTS=1 pytest -m llm tests/test_rag_live.py"""
import os

import pytest

from app.rag.service import RagService
from tests.test_rag import AS9100_A, ISO_B, doc

pytestmark = [pytest.mark.llm, pytest.mark.skipif(os.getenv("HAL_RUN_LLM_TESTS") != "1", reason="opt-in")]


def test_real_embedder_retrieval_and_isolation():
    from app.llm.embeddings import GraniteEmbedder

    rag = RagService(GraniteEmbedder())
    rag.index_document("e1", "vA", "dA", doc("a.pdf", [AS9100_A, "Scope: CNC machining of aerospace parts."]))
    rag.index_document("e1", "vB", "dB", doc("b.pdf", [ISO_B]))
    hits = rag.search("e1", "vA", "aerospace quality management certificate", k=2)
    assert hits[0].chunk.page_number == 1 and all(h.chunk.vendor_id == "vA" for h in hits)
    b_hits = rag.search("e1", "vB", "AS9100 aerospace quality", k=3)
    assert all(h.chunk.vendor_id == "vB" for h in b_hits)
    print([(h.chunk.vendor_id, round(h.score, 3)) for h in hits + b_hits])
