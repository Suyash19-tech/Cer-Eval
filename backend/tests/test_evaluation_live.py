"""Opt-in: real Granite LLM + embedder. HAL_RUN_LLM_TESTS=1 pytest -m llm tests/test_evaluation_live.py -s"""
import os

import pytest

from app.agents.criteria_extractor import extract_criteria
from app.evaluation import engine
from app.models import Evaluation, EvaluationCriterion
from app.rag.service import RagService
from app.schemas.documents import PageText, ProcessedDocument
from app.schemas.enums import DocumentClass
from tests.test_evaluation import comm_doc, tech_doc

pytestmark = [pytest.mark.llm, pytest.mark.skipif(os.getenv("HAL_RUN_LLM_TESTS") != "1", reason="opt-in")]

TENDER = """SYNTHETIC - NOT VALID FOR PROCUREMENT
3. Technical specifications
3.1 The pump shall deliver a maximum operating pressure of at least 250 bar.
3.2 The pump weight shall not exceed 15 kg.
3.3 The housing material shall be stainless steel.
4. Commercial conditions
4.1 Delivery shall be completed within 90 days of the purchase order.
4.2 The quotation shall remain valid for at least 60 days.
The vendor shall hold a valid AS9100 Rev D certificate."""


def pd(name, text, cls):
    return ProcessedDocument(filename=name, sha256="0" * 64, mime_type="application/pdf", page_count=1,
                             pages=[PageText(page_number=1, text=text[0], source="text_layer")], document_class=cls)


def test_real_models(db_session):
    from app.llm.embeddings import GraniteEmbedder
    from app.llm.granite import GraniteLLM

    llm = GraniteLLM()
    items = extract_criteria(llm, [PageText(page_number=1, text=TENDER, source="text_layer")])
    for i in items:
        print("CRIT", i["criterion_code"], i["kind"], i["name"], i["comparator"], i["required_value"], i["unit"],
              i["mandatory"], i["parameter"], i["needs_human_review"], i["review_reasons"])
    assert not any("AS9100" in i["supporting_text"] for i in items), "certification leaked into criteria"

    ev = Evaluation(name="T", tender_path="x", tender_sha256="0" * 64, workflow_status="RUNNING")
    db_session.add(ev)
    db_session.flush()
    from app.models import Vendor
    v = Vendor(evaluation_id=ev.id, name="Alpha", eligibility="PASS")
    db_session.add(v)
    db_session.flush()
    for i in items:
        db_session.add(EvaluationCriterion(evaluation_id=ev.id, confirmed=True, origin="LLM", **i))
    db_session.commit()
    rag = RagService(GraniteEmbedder())
    rag.index_document(ev.id, v.id, "d1", pd("tech.pdf", tech_doc("275 bar", "12 kg"), DocumentClass.TECHNICAL_QUOTATION))
    rag.index_document(ev.id, v.id, "d2", pd("comm.pdf", comm_doc(), DocumentClass.COMMERCIAL_QUOTATION))
    print("TECH", engine.run_technical(db_session, ev.id, v.id, rag, llm))
    for f in db_session.query(engine.CriterionFinding):
        print("FIND", f.criterion_code, f.status, f.reasons, f.evidence)
    print("COMM", engine.run_commercial(db_session, ev.id, v.id, rag, llm))
    print("SUMMARY", db_session.get(engine.CommercialSummary, v.id).data)
