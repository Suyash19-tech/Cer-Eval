"""Opt-in: real Granite LLM + real Granite embedder over synthetic certificate PDFs.
HAL_RUN_LLM_TESTS=1 pytest -m llm tests/test_screening_live.py -s"""
import os
from datetime import date

import pytest

from app.models import Evaluation, TenderRequirement
from tests.test_document_processing import make_pdf
from tests.test_screening import cert

pytestmark = [pytest.mark.llm, pytest.mark.skipif(os.getenv("HAL_RUN_LLM_TESTS") != "1", reason="opt-in")]


def test_real_models_screen_vendors(client, db_session, tmp_path):
    from app.api.dependencies import get_llm, get_rag
    from app.llm.embeddings import GraniteEmbedder
    from app.llm.granite import GraniteLLM
    from app.rag.service import RagService

    llm, rag = GraniteLLM(), RagService(GraniteEmbedder())
    client.app.dependency_overrides[get_llm] = lambda: llm
    client.app.dependency_overrides[get_rag] = lambda: rag
    ev = Evaluation(name="T", tender_path="x", tender_sha256="0" * 64, workflow_status="REQUIREMENTS_CONFIRMED")
    db_session.add(ev)
    db_session.flush()
    for code, cat, std, ver, name in (("REQ-X-001", "X", "AS9100", "D", "AS9100 Rev D"),
                                      ("REQ-OTH-001", "OTHER_CERTIFICATION", "ISO 14001", "2015", "ISO 14001:2015")):
        db_session.add(TenderRequirement(evaluation_id=ev.id, requirement_code=code, category=cat, description=name,
                                         mandatory=True, certificate_name=name, standard=std, version=ver,
                                         validation_conditions={"conditions": ["must be valid"]}, supporting_text=name,
                                         confirmed=True, origin="LLM"))
    db_session.commit()

    def run(name, certs):
        files = []
        for i, pages in enumerate(certs):
            p = make_pdf(tmp_path / f"{name}{i}.pdf", pages)
            files.append(("files", (p.name, p.read_bytes(), "application/pdf")))
        vid = client.post(f"/api/evaluations/{ev.id}/vendors", data={"name": name}, files=files).json()["id"]
        client.post(f"/api/evaluations/{ev.id}/vendors/{vid}/screen?as_of={date(2026, 11, 23)}")
        v = client.get(f"/api/evaluations/{ev.id}/vendors/{vid}").json()
        print(name, v["eligibility"], {f["requirement_code"]: (f["status"], f["reasons"]) for f in v["findings"]})
        return v

    good = run("Alpha Aero", [cert("Alpha Aero Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                              cert("Alpha Aero Ltd", "ISO 14001:2015", "Valid until 2028-06-30")])
    old = run("Delta Tech", [cert("Delta Tech Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                             cert("Delta Tech Ltd", "ISO 14001:2015", "Valid until 2025-03-01")])
    miss = run("Beta Works", [cert("Beta Works Ltd", "AS9100 Rev D", "Valid until 2028-06-30")])
    assert good["screening_status"] == "DONE"
    assert good["eligibility"] == "PASS"
    assert old["eligibility"] == "FAIL" and miss["eligibility"] == "FAIL"
