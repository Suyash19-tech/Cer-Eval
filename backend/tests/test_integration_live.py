"""Opt-in: the SYNTHETIC five-vendor dataset with the REAL local Granite LLM + Granite embedder (+ real OCR).
HAL_RUN_LLM_TESTS=1 pytest -m llm tests/test_integration_live.py -s

A scripted 'reviewer' stands in for the human at confirmation time: it accepts only what the ground-truth file says the
tender contains and rejects everything else with a reason (it never invents or edits values).
"""
import os

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_llm, get_rag, get_workflow_graph
from app.graph.workflow import WorkflowDeps, build_workflow, with_real_evaluators
from app.models import CommercialSummary, CriterionFinding
from tests.conftest import REVIEWER_HEADERS
from tests.test_integration_dataset import files_for, load_generator, names, standard_by_code

pytestmark = [pytest.mark.llm, pytest.mark.skipif(os.getenv("HAL_RUN_LLM_TESTS") != "1", reason="opt-in")]


def test_dataset_with_real_models(client, engine, db_session, tmp_path, monkeypatch):
    from app.llm.embeddings import GraniteEmbedder
    from app.llm.granite import GraniteLLM
    from app.rag.service import RagService
    from app.services import workflow_service

    monkeypatch.setattr(workflow_service, "MAX_CONCURRENCY", 1)
    root = tmp_path / "synthetic"
    exp = load_generator().build(root)
    llm, rag = GraniteLLM(), RagService(GraniteEmbedder())
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client.app.dependency_overrides[get_llm] = lambda: llm
    client.app.dependency_overrides[get_rag] = lambda: rag
    deps = with_real_evaluators(WorkflowDeps(session_factory=factory, llm=llm, rag=rag, reports_dir=tmp_path / "reports"))
    graph = build_workflow(deps, MemorySaver())
    client.app.dependency_overrides[get_workflow_graph] = lambda: graph
    c, db = client, db_session

    eid = c.post("/api/evaluations", data={"name": "SYN live"},
                 files={"tender": ("tender.pdf", (root / "tender.pdf").read_bytes(), "application/pdf")}).json()["id"]
    db.expire_all()
    ev = c.get(f"/api/evaluations/{eid}").json()
    assert ev["workflow_status"] == "REQUIREMENTS_PENDING_CONFIRMATION", ev["error"]
    wanted = {(e["standard"]) for e in exp["tender_requirements"]}
    decisions = []
    for q in ev["requirements"]:
        print("REQ", q["requirement_code"], q["category"], q["standard"], q["version"], q["mandatory"], q["needs_human_review"], q["review_reasons"])
        if "months validity" in q["supporting_text"]:  # a general eligibility condition, not a certificate: reviewer re-labels it
            decisions.append({"requirement_id": q["requirement_code"], "action": "edit",
                              "edits": {"category": "ELIGIBILITY_CONDITION"}})
            continue
        ok = q["standard"] in wanted
        decisions.append({"requirement_id": q["requirement_code"], "action": "accept" if ok else "reject",
                          "reason": None if ok else "Not a certification requirement of the synthetic tender"})
    r = c.post(f"/api/evaluations/{eid}/requirements/confirm", json={"decisions": decisions}, headers=REVIEWER_HEADERS)
    assert r.status_code == 200, r.text
    std = standard_by_code({"reqs": {q["requirement_code"]: q for q in c.get(f"/api/evaluations/{eid}").json()["requirements"]
                                     if q["confirmed"]}})
    assert set(std.values()) == wanted

    c.post(f"/api/evaluations/{eid}/criteria/extract")
    db.expire_all()
    crit = c.get(f"/api/evaluations/{eid}/criteria").json()
    cd = []
    for k in crit["criteria"]:
        print("CRIT", k["criterion_code"], k["kind"], k["name"], k["comparator"], k["required_value"], k["unit"], k["parameter"], k["needs_human_review"])
        cd.append({"criterion_code": k["criterion_code"], "action": "reject" if k["needs_human_review"] else "accept",
                   "reason": "Flagged by the verifier; rejected by the scripted reviewer" if k["needs_human_review"] else None})
    assert len(crit["criteria"]) == 4 and not any(k["needs_human_review"] for k in crit["criteria"]), "real Granite should find all 4 criteria"
    assert c.post(f"/api/evaluations/{eid}/criteria/confirm", json={"decisions": cd}, headers=REVIEWER_HEADERS).status_code == 200

    ids = {}
    for label, v in exp["vendors"].items():
        r = c.post(f"/api/evaluations/{eid}/vendors", data={"name": v["name"]}, files=files_for(root, label))
        assert r.status_code == 201, r.text
        ids[label] = r.json()["id"]
    c.post(f"/api/evaluations/{eid}/workflow/start?as_of={exp['as_of']}")
    vendors = {x["id"]: x for x in c.get(f"/api/evaluations/{eid}/vendors").json()}
    for label, e in exp["vendors"].items():
        got = vendors[ids[label]]
        print("VENDOR", label, got["eligibility"], {f["requirement_code"]: f["status"] for f in got["findings"]})
        assert got["eligibility"] == e["certification"], (label, got["eligibility_reason"])
        assert {std[f["requirement_code"]]: f["status"] for f in got["findings"] if f["requirement_code"] in std} == e["findings"], label
    evaluated = {f.vendor_id for f in db.query(CriterionFinding)} | {s.vendor_id for s in db.query(CommercialSummary)}
    assert not evaluated & {ids["B"], ids["D"], ids["E"]}  # failed / pending vendors never entered downstream evaluation
    res = {r["name"]: r for r in c.get(f"/api/evaluations/{eid}/results").json()["vendors"]}
    for label in "AC":
        r = res[exp["vendors"][label]["name"]]
        print("RESULT", label, r["technical"]["status"], r["commercial"]["status"], r["commercial"]["total_price"], r["rank"])
        assert (r["technical"]["status"], r["commercial"]["status"]) == ("QUALIFIED", "VALID")
        assert r["commercial"]["total_price"] == exp["vendors"][label]["total_price"]
    assert [res[exp["vendors"][l]["name"]]["rank"] for l in "AC"] == [1, 2]
    assert c.get(f"/api/evaluations/{eid}/workflow").json()["awaiting_human_review"]
    # human resolves E, workflow resumes, E joins the ranking (A, E, C)
    ereq = next(code for code, s_ in std.items() if s_ == "ISO 14001")
    r = c.post(f"/api/evaluations/{eid}/vendors/{ids['E']}/review", headers=REVIEWER_HEADERS,
               json={"requirement_code": ereq, "decision": "COMPLIANT", "reason": "Original shows expiry 3 April 2028 (day-first)"})
    assert r.json()["eligibility"] == "PASS"
    c.post(f"/api/evaluations/{eid}/workflow/resume", headers=REVIEWER_HEADERS)
    final = c.get(f"/api/evaluations/{eid}/results").json()
    by_id = {x["vendor_id"]: x for x in final["vendors"]}
    print("FINAL", [by_id[i]["name"] for i in final["ranking"]])
    assert [by_id[i]["name"] for i in final["ranking"]] == names({"expected": exp}, exp["ranking_after_review"])
    assert c.get(f"/api/evaluations/{eid}/workflow").json()["workflow_status"] == "COMPLETED"
    assert not {f.vendor_id for f in db.query(CriterionFinding)} & {ids["B"], ids["D"]}
