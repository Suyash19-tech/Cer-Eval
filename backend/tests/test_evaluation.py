import io

import pytest
from langgraph.checkpoint.memory import MemorySaver
from openpyxl import load_workbook
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_llm, get_rag, get_workflow_graph
from app.evaluation import engine
from app.evaluation.money import parse_days, parse_money
from app.evaluation.units import convert
from app.graph.workflow import WorkflowDeps, build_workflow, with_real_evaluators
from app.models import CommercialSummary, CriterionFinding, Evaluation, EvaluationCriterion
from app.schemas.criteria import (
    LLMCommercial, LLMCriterion, LLMCriterionList, QuotedText, SpecProposal, SpecProposalList,
)
from tests.conftest import REVIEWER_HEADERS
from tests.test_document_processing import make_pdf
from tests.test_screening import CertLLM, cert, setup  # noqa: F401


def tech_doc(pressure="275 bar", weight="12 kg"):
    lines = ["SYNTHETIC - NOT VALID FOR PROCUREMENT", "Technical quotation and technical compliance statement"]
    if pressure:
        lines.append(f"Maximum operating pressure: {pressure}.")
    if weight:
        lines.append(f"Weight: {weight}.")
    return ["\n".join(lines)]


def comm_doc(total="INR 1,000,000", unit="INR 100,000", qty="10 units", delivery="60 days", payment="30 days net"):
    return ["\n".join(["SYNTHETIC - NOT VALID FOR PROCUREMENT", "Commercial quotation", f"Quantity: {qty}.",
                       f"Unit price: {unit}.", f"Total price: {total}.", "GST 18%: INR 180,000.",
                       f"Delivery within {delivery}.", f"Payment terms: {payment}.", "Quotation valid for 90 days."])]


class EvalLLM(CertLLM):
    """Scripted stand-in for Granite: quotes the lines it can see; never computes anything."""

    def extract(self, schema, instruction, document_text, max_tokens=1024):
        if schema is SpecProposalList:
            name = document_text.split("\n", 1)[0].split(":", 1)[1].split("(")[0].strip().lower()
            lines = [l for l in document_text.splitlines()[1:] if l.lower().startswith(name)]
            return SpecProposalList(values=[SpecProposal(supporting_text=l) for l in lines])
        if schema is LLMCommercial:
            lines = document_text.splitlines()
            f = lambda *p: next((QuotedText(text=l) for l in lines if l.lower().startswith(p)), None)  # noqa: E731
            return LLMCommercial(total_price=f("total price"), unit_price=f("unit price"), quantity=f("quantity"),
                                 taxes=f("gst"), delivery_terms=f("delivery"), payment_terms=f("payment"),
                                 price_validity=f("quotation valid"))
        return super().extract(schema, instruction, document_text, max_tokens)


@pytest.fixture
def ev(client, engine, setup, tmp_path, monkeypatch, db_session):  # noqa: F811
    from app.services import workflow_service
    monkeypatch.setattr(workflow_service, "MAX_CONCURRENCY", 1)
    rag = client.app.dependency_overrides[get_rag]()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    llm = EvalLLM()
    client.app.dependency_overrides[get_llm] = lambda: llm
    deps = with_real_evaluators(WorkflowDeps(session_factory=factory, llm=llm, rag=rag, reports_dir=tmp_path / "reports"))
    graph = build_workflow(deps, MemorySaver())
    client.app.dependency_overrides[get_workflow_graph] = lambda: graph
    e = db_session.get(Evaluation, setup)

    def crit(code, kind, name, cmp, val, unit, mandatory=True, parameter=None, weight=1.0):
        db_session.add(EvaluationCriterion(evaluation_id=setup, criterion_code=code, kind=kind, name=name, parameter=parameter,
                                           comparator=cmp, required_value=val, unit=unit, mandatory=mandatory, weight=weight,
                                           supporting_text=name, confirmed=True))
    crit("TECH-001", "TECHNICAL", "Maximum operating pressure", "GTE", 250, "bar")
    crit("TECH-002", "TECHNICAL", "Weight", "LTE", 15, "kg", mandatory=False)
    crit("COM-001", "COMMERCIAL", "Delivery period", "LTE", 90, "days", parameter="delivery_days")
    e.criteria_status = "CONFIRMED"
    db_session.commit()
    return {"eid": setup, "tmp": tmp_path, "factory": factory, "db": db_session}


def add(client, ev, name, pdfs):
    files = []
    for i, pages in enumerate(pdfs):
        p = make_pdf(ev["tmp"] / f"{abs(hash((name, i)))}.pdf", pages)
        files.append(("files", (p.name, p.read_bytes(), "application/pdf")))
    r = client.post(f"/api/evaluations/{ev['eid']}/vendors", data={"name": name}, files=files)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ok_certs(h):
    return [cert(h, "AS9100 Rev D", "Valid until 2028-06-30"), cert(h, "ISO 14001:2015", "Valid until 2028-06-30")]


def populate(client, ev):
    ids = {
        "Alpha": add(client, ev, "Alpha", ok_certs("Alpha Ltd") + [tech_doc("275 bar"), comm_doc()]),
        "Beta": add(client, ev, "Beta", [cert("Beta Ltd", "AS9100 Rev D", "Valid until 2028-06-30"), tech_doc(), comm_doc()]),
        "Gamma": add(client, ev, "Gamma", ok_certs("Gamma Ltd") + [tech_doc("260 bar", "14 kg"),
                                                                     comm_doc("INR 1,250,000", "INR 125,000")]),
        "Delta": add(client, ev, "Delta", [cert("Delta Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                                           cert("Delta Ltd", "ISO 14001:2015", "Valid until 2025-03-01"), tech_doc(), comm_doc()]),
        "Echo": add(client, ev, "Echo", [cert("Echo Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                                         cert("Echo Ltd", "ISO 14001:2015", "Valid until 03/04/2028"),
                                         tech_doc("240 bar"), comm_doc()]),
    }
    return ids


def run_wf(client, eid):
    assert client.post(f"/api/evaluations/{eid}/workflow/start?as_of=2026-11-23").status_code == 202
    return client.get(f"/api/evaluations/{eid}/workflow").json()


def res(client, eid):
    return {v["name"]: v for v in client.get(f"/api/evaluations/{eid}/results").json()["vendors"]}


# ---- pure helpers ----------------------------------------------------------------------------
def test_money_and_durations():
    assert parse_money("Total price: INR 1,250,000.50")[0].amount == 1250000.5
    assert parse_money("GST 18%") == []  # a percentage is not money
    assert parse_days("Delivery within 12 weeks") == (84.0, None)
    assert parse_days("Delivery 30 days or 60 days")[0] is None
    assert convert(25, "mpa", "bar") == 250


# ---- gate: failed / pending vendors never evaluated ----------------------------------------------
def test_only_certified_vendors_are_evaluated_and_ranked(client, ev):
    ids = populate(client, ev)
    run_wf(client, ev["eid"])
    db = ev["db"]
    db.expire_all()
    evaluated = {f.vendor_id for f in db.query(CriterionFinding)}
    assert evaluated == {ids["Alpha"], ids["Gamma"]}  # Beta, Delta (FAIL) and Echo (PENDING) never touched
    assert {s.vendor_id for s in db.query(CommercialSummary)} == {ids["Alpha"], ids["Gamma"]}
    r = res(client, ev["eid"])
    for n in ("Beta", "Delta", "Echo"):
        assert r[n]["technical"]["status"] == "NOT_EVALUATED" and r[n]["commercial"]["status"] == "NOT_EVALUATED"
        assert not r[n]["ranked"]
    assert r["Alpha"]["technical"] == {**r["Alpha"]["technical"], "status": "QUALIFIED", "score": 100.0}
    assert r["Alpha"]["commercial"]["status"] == "VALID" and r["Alpha"]["commercial"]["total_price"] == 1000000
    assert (r["Alpha"]["rank"], r["Alpha"]["combined_score"], r["Alpha"]["price_score"]) == (1, 100.0, 100.0)
    assert (r["Gamma"]["rank"], r["Gamma"]["price_score"], r["Gamma"]["combined_score"]) == (2, 80.0, 90.0)
    assert client.get(f"/api/evaluations/{ev['eid']}/results").json()["ranking"] == [ids["Alpha"], ids["Gamma"]]


def test_deviation_disqualifies_and_dependency_skips_commercial(client, ev):
    ids = populate(client, ev)
    run_wf(client, ev["eid"])
    client.post(f"/api/evaluations/{ev['eid']}/vendors/{ids['Echo']}/review", headers=REVIEWER_HEADERS,
                json={"requirement_code": "REQ-OTH-001", "decision": "COMPLIANT", "reason": "Verified original certificate"})
    client.post(f"/api/evaluations/{ev['eid']}/workflow/resume", headers=REVIEWER_HEADERS)
    s = client.get(f"/api/evaluations/{ev['eid']}/workflow").json()
    echo = s["vendor_results"][ids["Echo"]]
    assert echo["technical"]["status"] == "NOT_QUALIFIED" and "TECH-001" in echo["technical"]["reason"]  # 240 < 250 bar
    assert echo["commercial"]["status"] == "SKIPPED"
    r = res(client, ev["eid"])
    assert not r["Echo"]["ranked"] and r["Echo"]["technical"]["status"] == "NOT_QUALIFIED"


def test_config_without_dependency_still_runs_commercial(client, ev):
    ids = populate(client, ev)
    ev["db"].get(Evaluation, ev["eid"]).evaluation_config = {"second_stage_requires_first_qualified": False}
    ev["db"].commit()
    run_wf(client, ev["eid"])
    client.post(f"/api/evaluations/{ev['eid']}/vendors/{ids['Echo']}/review", headers=REVIEWER_HEADERS,
                json={"requirement_code": "REQ-OTH-001", "decision": "COMPLIANT", "reason": "Verified original certificate"})
    client.post(f"/api/evaluations/{ev['eid']}/workflow/resume", headers=REVIEWER_HEADERS)
    echo = client.get(f"/api/evaluations/{ev['eid']}/workflow").json()["vendor_results"][ids["Echo"]]
    assert echo["technical"]["status"] == "NOT_QUALIFIED" and echo["commercial"]["status"] == "VALID"


def test_commercial_first_order_is_configurable(client, ev):
    populate(client, ev)
    ev["db"].get(Evaluation, ev["eid"]).evaluation_config = {"order": "commercial_first"}
    ev["db"].commit()
    s = run_wf(client, ev["eid"])
    order = [e["node"] for e in s["node_log"] if e.get("vendor_id")]
    alpha_stages = [n for n in order if n.endswith("_evaluation")]
    assert alpha_stages[0] == "commercial_evaluation" and "technical_evaluation" in alpha_stages


# ---- honesty: never invent --------------------------------------------------------------------
def test_missing_spec_is_flagged_not_invented(client, ev):
    vid = add(client, ev, "Alpha", ok_certs("Alpha Ltd") + [tech_doc(pressure=None), comm_doc()])
    run_wf(client, ev["eid"])
    f = {x.criterion_code: x for x in ev["db"].query(CriterionFinding).filter_by(vendor_id=vid)}
    assert f["TECH-001"].status == "MISSING_DETAIL" and f["TECH-001"].evidence == {}
    r = res(client, ev["eid"])["Alpha"]
    assert r["technical"]["status"] == "NEEDS_REVIEW" and not r["ranked"]
    # a reviewer resolves it; the resolution is audited and recomputed
    url = f"/api/evaluations/{ev['eid']}/vendors/{vid}/criteria/review"
    body = {"criterion_code": "TECH-001", "decision": "MEETS", "reason": "Clarification letter confirms 260 bar"}
    assert client.post(url, json=body).status_code == 401
    out = client.post(url, json=body, headers=REVIEWER_HEADERS).json()
    assert out["technical"]["status"] == "QUALIFIED"
    assert client.post(url, json=body, headers=REVIEWER_HEADERS).status_code == 409


def test_vendor_without_commercial_quotation_has_no_invented_price(client, ev):
    add(client, ev, "Alpha", ok_certs("Alpha Ltd") + [tech_doc()])
    run_wf(client, ev["eid"])
    r = res(client, ev["eid"])["Alpha"]["commercial"]
    assert r["status"] == "NEEDS_REVIEW" and r["total_price"] is None and "Total price not stated" in r["reason"]


def test_price_components_that_do_not_reconcile_need_review(client, ev):
    add(client, ev, "Alpha", ok_certs("Alpha Ltd") + [tech_doc(), comm_doc(total="INR 900,000")])
    run_wf(client, ev["eid"])
    r = res(client, ev["eid"])["Alpha"]["commercial"]
    assert r["status"] == "NEEDS_REVIEW" and "do not reconcile" in r["reason"]


@pytest.mark.parametrize("delivery,status", [("14 weeks", "NOT_QUALIFIED"), ("12 weeks", "VALID")])
def test_delivery_unit_conversion_against_tender_limit(client, ev, delivery, status):
    add(client, ev, "Alpha", ok_certs("Alpha Ltd") + [tech_doc(), comm_doc(delivery=delivery)])
    ev["db"].get(Evaluation, ev["eid"]).evaluation_config = {"order": "independent"}
    ev["db"].commit()
    run_wf(client, ev["eid"])
    r = res(client, ev["eid"])["Alpha"]["commercial"]
    assert r["status"] == status  # 14 weeks = 98 days > 90; 12 weeks = 84 days <= 90
    if status == "NOT_QUALIFIED":
        assert "COM-001" in r["reason"]


def test_review_endpoint_rejects_failed_vendor(client, ev):
    ids = populate(client, ev)
    run_wf(client, ev["eid"])
    body = {"criterion_code": "TECH-001", "decision": "MEETS", "reason": "trying to push a failed vendor"}
    r = client.post(f"/api/evaluations/{ev['eid']}/vendors/{ids['Beta']}/criteria/review", json=body, headers=REVIEWER_HEADERS)
    assert r.status_code == 409


# ---- reports --------------------------------------------------------------------------------
def wb(client, eid, kind):
    r = client.get(f"/api/evaluations/{eid}/reports/{kind}")
    assert r.status_code == 200
    return load_workbook(io.BytesIO(r.content))


def table(ws):
    rows = list(ws.iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:]]


def test_reports_never_show_failed_vendors_as_evaluated(client, ev):
    populate(client, ev)
    run_wf(client, ev["eid"])
    tech = wb(client, ev["eid"], "technical")
    assert {r["Vendor"] for r in table(tech["Technical Criteria"])} == {"Alpha", "Gamma"}
    comm = wb(client, ev["eid"], "commercial")
    by = {r["Vendor"]: r for r in table(comm["Commercial Summary"])}
    assert by["Alpha"]["Total Price"] == 1000000 and by["Beta"]["Commercial Status"] == "NOT_EVALUATED"
    assert by["Beta"]["Total Price"] is None
    con = {r["Vendor"]: r for r in table(wb(client, ev["eid"], "consolidated")["Final Comparison"])}
    assert con["Beta"]["Technical"] == "NOT_EVALUATED" and con["Beta"]["Rank"] is None
    assert "Certification failed" in con["Beta"]["Rejection / Pending Reason"]
    assert "Certification failed" in con["Delta"]["Rejection / Pending Reason"]
    assert "Pending human review" in con["Echo"]["Rejection / Pending Reason"]
    assert (con["Alpha"]["Rank"], con["Gamma"]["Rank"]) == (1, 2)


# ---- criteria extraction + confirmation --------------------------------------------------------
def test_criteria_extraction_and_confirmation(client, ev, db_session):
    e = db_session.get(Evaluation, ev["eid"])
    e.criteria_status = "NOT_STARTED"
    e.tender_pages = [{"page_number": 3, "source": "text_layer",
                       "text": "3.1 The pump shall deliver a maximum operating pressure of at least 250 bar.\n"
                               "3.2 Delivery shall be completed within 90 days of the purchase order.\n"
                               "3.3 The vendor shall provide an excellent service."}]
    db_session.query(EvaluationCriterion).delete()
    db_session.commit()
    llm = EvalLLM()
    quote = lambda n: e.tender_pages[0]["text"].splitlines()[n]  # noqa: E731
    items = [
        LLMCriterion(kind="TECHNICAL", name="Max operating pressure", comparator="GTE", required_value=250, unit="bar",
                     mandatory=True, supporting_text=quote(0)),
        LLMCriterion(kind="COMMERCIAL", name="Delivery period", parameter="delivery_days", comparator="LTE",
                     required_value=90, unit="days", mandatory=True, supporting_text=quote(1)),
        LLMCriterion(kind="TECHNICAL", name="Service quality", comparator="GTE", required_value=99, unit=None,
                     mandatory=True, supporting_text="The vendor shall provide a fantastic invented service."),  # hallucinated
    ]
    llm.extract = lambda schema, instr, text, max_tokens=1024: LLMCriterionList(criteria=items)
    client.app.dependency_overrides[get_llm] = lambda: llm
    assert client.post(f"/api/evaluations/{ev['eid']}/criteria/extract").status_code == 202
    db_session.expire_all()
    data = client.get(f"/api/evaluations/{ev['eid']}/criteria").json()
    assert data["criteria_status"] == "PENDING_CONFIRMATION"
    by = {c["criterion_code"]: c for c in data["criteria"]}
    assert by["TECH-001"]["source_page"] == 3 and not by["TECH-001"]["needs_human_review"]
    assert by["COM-001"]["parameter"] == "delivery_days"
    assert by["TECH-002"]["needs_human_review"] and by["TECH-002"]["source_page"] is None  # hallucination flagged
    assert not any(c["confirmed"] for c in data["criteria"])
    url = f"/api/evaluations/{ev['eid']}/criteria/confirm"
    assert client.post(url, json={}).status_code == 401
    assert client.post(url, json={}, headers=REVIEWER_HEADERS).status_code == 422  # flagged item needs a decision
    bad_cfg = {"decisions": [{"criterion_code": "TECH-002", "action": "reject", "reason": "Not in the tender"}],
               "config": {"weight_technical": 0.9, "weight_commercial": 0.3}}
    assert client.post(url, json=bad_cfg, headers=REVIEWER_HEADERS).status_code == 422
    good = {"decisions": [{"criterion_code": "TECH-002", "action": "reject", "reason": "Not in the tender"},
                          {"criterion_code": "TECH-001", "action": "edit", "edit": {"weight": 3}}],
            "config": {"order": "commercial_first", "weight_technical": 0.7, "weight_commercial": 0.3}}
    r = client.post(url, json=good, headers=REVIEWER_HEADERS)
    assert r.status_code == 200 and r.json()["config"]["order"] == "commercial_first"
    db_session.expire_all()
    rows = {c.criterion_code: c for c in db_session.query(EvaluationCriterion)}
    assert rows["TECH-001"].weight == 3 and rows["TECH-001"].confirmed and rows["TECH-002"].rejected
    assert client.post(url, json={}, headers=REVIEWER_HEADERS).status_code == 409


def test_reviewer_can_add_a_missed_criterion_only_if_quoted_from_tender(client, ev, db_session):
    e = db_session.get(Evaluation, ev["eid"])
    e.criteria_status = "PENDING_CONFIRMATION"
    e.tender_pages = [{"page_number": 4, "source": "text_layer",
                       "text": "4.2 The pump shall operate at ambient temperatures up to 55 degC."}]
    db_session.commit()
    url = f"/api/evaluations/{ev['eid']}/criteria"
    body = {"kind": "TECHNICAL", "name": "Ambient temperature", "comparator": "GTE", "required_value": 55, "unit": "degC",
            "supporting_text": "The pump shall operate at ambient temperatures up to 55 degC.",
            "reason": "Extraction skipped this clause"}
    assert client.post(url, json=body).status_code == 401
    r = client.post(url, json=body, headers=REVIEWER_HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["criterion_code"] == "TECH-003" and r.json()["source_page"] == 4 and not r.json()["confirmed"]
    invented = {**body, "supporting_text": "The pump shall be painted bright green in all conditions."}
    assert client.post(url, json=invented, headers=REVIEWER_HEADERS).status_code == 422
    no_value = {**body, "required_value": None}
    assert client.post(url, json=no_value, headers=REVIEWER_HEADERS).status_code == 422
    bad_param = {**body, "kind": "COMMERCIAL", "parameter": "bribe_amount"}
    assert client.post(url, json=bad_param, headers=REVIEWER_HEADERS).status_code == 422
    # it is confirmed with the rest, and added criteria are audited
    assert client.post(f"{url}/confirm", json={}, headers=REVIEWER_HEADERS).status_code == 200
    db_session.expire_all()
    row = db_session.query(EvaluationCriterion).filter_by(criterion_code="TECH-003").one()
    assert row.confirmed and row.origin == "HUMAN"
    assert client.post(url, json=body, headers=REVIEWER_HEADERS).status_code == 409  # locked after confirmation
