"""Phase 11: the whole five-vendor SYNTHETIC dataset through the real API, workflow, document processing (text layer, OCR,
ZIP), RAG, deterministic validation, gate, human review, evaluation, ranking and reports.

Ground truth comes from data written by scripts/generate_synthetic_data.py, not from the system under test.
Fast mode (default): scripted LLM that only quotes lines + hash embedder; OCR is the REAL docTR/Tesseract engine.
Live mode: tests/test_integration_live.py runs the same checks with the real Granite models (opt-in).
"""

import importlib.util
import io
import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from openpyxl import load_workbook
from sqlalchemy.orm import sessionmaker

from app.agents.tender_extractor import derive_standard
from app.api.dependencies import get_llm, get_rag, get_workflow_graph
from app.graph.workflow import WorkflowDeps, build_workflow, with_real_evaluators
from app.models import CommercialSummary, CriterionFinding, Document
from app.rag.service import RagService
from app.schemas.criteria import LLMCriterion, LLMCriterionList
from app.schemas.requirements import LLMRequirement, LLMRequirementList
from tests.conftest import REVIEWER_HEADERS
from tests.test_evaluation import EvalLLM
from tests.test_rag import HashEmbedder

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_synthetic_data.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_synthetic_data", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DatasetLLM(EvalLLM):
    """Scripted reader for the synthetic tender: quotes clauses verbatim (test scaffolding, not an evaluation oracle)."""

    def extract(self, schema, instruction, document_text, max_tokens=1024):
        lines = [l.strip() for l in document_text.splitlines()]
        if schema is LLMRequirementList:
            out = []
            for l in lines:
                if "shall hold a valid" in l:
                    std, ver = derive_standard(l)
                    cat = "X" if "Category X" in l else "Y" if "Category Y" in l else "OTHER_CERTIFICATION"
                    out.append(LLMRequirement(category=cat, description=f"Valid {std} {ver} certificate", mandatory=True,
                                              certificate_name=f"{std} {ver}", standard=std, version=ver,
                                              validation_conditions=["must be valid"], supporting_text=l))
                elif "months validity remaining" in l:
                    out.append(LLMRequirement(category="ELIGIBILITY_CONDITION", description=l, mandatory=True,
                                              validation_conditions=[l], supporting_text=l))
            return LLMRequirementList(requirements=out)
        if schema is LLMCriterionList:
            out = []
            for l in lines:
                if "maximum operating pressure" in l:
                    out.append(LLMCriterion(kind="TECHNICAL", name="Maximum operating pressure", comparator="GTE",
                                            required_value=250, unit="bar", mandatory=True, supporting_text=l))
                elif "pump weight" in l:
                    out.append(LLMCriterion(kind="TECHNICAL", name="Weight", comparator="LTE", required_value=15,
                                            unit="kg", mandatory=True, supporting_text=l))
                elif l.startswith("3.1 Delivery"):
                    out.append(LLMCriterion(kind="COMMERCIAL", name="Delivery period", parameter="delivery_days",
                                            comparator="LTE", required_value=90, unit="days", mandatory=True, supporting_text=l))
                elif l.startswith("3.2 The quotation"):
                    out.append(LLMCriterion(kind="COMMERCIAL", name="Quotation validity", parameter="validity_days",
                                            comparator="GTE", required_value=60, unit="days", mandatory=True, supporting_text=l))
            return LLMCriterionList(criteria=out)
        return super().extract(schema, instruction, document_text, max_tokens)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    expected = load_generator().build(out)
    return out, expected


@pytest.fixture
def system(client, engine, db_session, tmp_path, monkeypatch, dataset):
    from app.services import workflow_service
    monkeypatch.setattr(workflow_service, "MAX_CONCURRENCY", 1)  # tests share one in-memory SQLite connection
    root, expected = dataset
    llm = DatasetLLM()
    rag = RagService(HashEmbedder())
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client.app.dependency_overrides[get_llm] = lambda: llm
    client.app.dependency_overrides[get_rag] = lambda: rag
    deps = with_real_evaluators(WorkflowDeps(session_factory=factory, llm=llm, rag=rag, reports_dir=tmp_path / "reports"))
    graph = build_workflow(deps, MemorySaver())
    client.app.dependency_overrides[get_workflow_graph] = lambda: graph
    return {"client": client, "root": root, "expected": expected, "db": db_session}


def files_for(root: Path, label: str):
    return [("files", (p.name, p.read_bytes(), "application/zip" if p.suffix == ".zip" else "application/octet-stream"))
            for p in sorted((root / "vendors" / label).iterdir())]


def run_dataset_until_review(s) -> dict:
    """Upload tender -> confirm -> add vendors -> run workflow. Returns ids by label."""
    c, root, db = s["client"], s["root"], s["db"]
    r = c.post("/api/evaluations", data={"name": "SYN-2026-001"},
               files={"tender": ("tender.pdf", (root / "tender.pdf").read_bytes(), "application/pdf")})
    assert r.status_code == 202
    eid = r.json()["id"]
    db.expire_all()
    ev = c.get(f"/api/evaluations/{eid}").json()
    assert ev["workflow_status"] == "REQUIREMENTS_PENDING_CONFIRMATION"
    reqs = {q["requirement_code"]: q for q in ev["requirements"]}
    certs = [q for q in reqs.values() if q["category"] != "ELIGIBILITY_CONDITION"]
    assert {(q["standard"], q["version"], q["category"]) for q in certs} == {
        (e["standard"], e["version"], e["category"]) for e in s["expected"]["tender_requirements"]}
    assert not any(q["needs_human_review"] for q in reqs.values()) and not any(q["confirmed"] for q in reqs.values())
    assert c.post(f"/api/evaluations/{eid}/requirements/confirm", json={}, headers=REVIEWER_HEADERS).status_code == 200
    assert c.post(f"/api/evaluations/{eid}/criteria/extract").status_code == 202
    db.expire_all()
    crit = c.get(f"/api/evaluations/{eid}/criteria").json()
    assert crit["criteria_status"] == "PENDING_CONFIRMATION" and len(crit["criteria"]) == 4
    assert c.post(f"/api/evaluations/{eid}/criteria/confirm", json={}, headers=REVIEWER_HEADERS).status_code == 200
    ids = {}
    for label, v in s["expected"]["vendors"].items():
        r = c.post(f"/api/evaluations/{eid}/vendors", data={"name": v["name"]}, files=files_for(root, label))
        assert r.status_code == 201, r.text
        ids[label] = r.json()["id"]
    s["eid"], s["ids"], s["reqs"] = eid, ids, reqs
    assert c.post(f"/api/evaluations/{eid}/workflow/start?as_of={s['expected']['as_of']}").status_code == 202
    return ids


def standard_by_code(s):
    return {code: q["standard"] for code, q in s["reqs"].items() if q["standard"]}


def names(s, labels):
    return [s["expected"]["vendors"][l]["name"] for l in labels]


def test_documents_are_classified_and_ocr_used(system):
    ids = run_dataset_until_review(system)
    db = system["db"]
    docs = {l: db.query(Document).filter_by(vendor_id=i).all() for l, i in ids.items()}
    assert {l: len(d) for l, d in docs.items()} == {"A": 4, "B": 3, "C": 5, "D": 4, "E": 4}  # ZIPs were unpacked
    classes = {l: sorted(d.document_class for d in ds) for l, ds in docs.items()}
    assert classes["A"] == ["COMMERCIAL_QUOTATION", "OTHER_CERTIFICATION", "OTHER_CERTIFICATION", "TECHNICAL_QUOTATION"]
    assert not any(d.needs_flag for ds in docs.values() for d in ds if d.document_class != "SUPPORTING_DOCUMENT")
    ocr_docs = [d.filename for d in docs["C"] if any(p["source"] == "ocr" for p in d.pages)]
    assert sorted(ocr_docs) == ["C_AS9100_certificate_scan.pdf", "C_ISO14001_certificate.png"]  # scanned + image: real OCR
    assert all(p["source"] == "text_layer" for ds in (docs["A"], docs["B"]) for d in ds for p in d.pages)


def test_full_dataset_matches_expected_results(system):
    c, db, exp = system["client"], system["db"], system["expected"]
    ids = run_dataset_until_review(system)
    eid = system["eid"]
    std = standard_by_code(system)
    v = {r["id"]: r for r in c.get(f"/api/evaluations/{eid}/vendors").json()}
    for label, e in exp["vendors"].items():
        got = v[ids[label]]
        assert got["eligibility"] == e["certification"], (label, got["eligibility_reason"])
        assert {std[f["requirement_code"]]: f["status"] for f in got["findings"] if f["requirement_code"] in std} == e["findings"], label
    # the gate: failed vendors never reach downstream evaluation
    evaluated = {f.vendor_id for f in db.query(CriterionFinding)} | {s.vendor_id for s in db.query(CommercialSummary)}
    assert evaluated == {ids[l] for l, e in exp["vendors"].items() if e["downstream"]} == {ids["A"], ids["C"]}
    assert not evaluated & {ids[l] for l in exp["never_downstream"]}
    results = {r["name"]: r for r in c.get(f"/api/evaluations/{eid}/results").json()["vendors"]}
    for label, e in exp["vendors"].items():
        r = results[e["name"]]
        if e["downstream"]:
            assert (r["technical"]["status"], r["commercial"]["status"]) == (e["technical"], e["commercial"]), label
            assert r["commercial"]["total_price"] == e["total_price"]
        else:
            assert r["technical"]["status"] == r["commercial"]["status"] == "NOT_EVALUATED" and not r["ranked"], label
    assert [r["name"] for r in sorted((r for r in results.values() if r["ranked"]), key=lambda x: x["rank"])] == names(system, exp["ranking_before_review"])
    # Vendor E waits for a human; the workflow is paused, not finished
    wf = c.get(f"/api/evaluations/{eid}/workflow").json()
    assert wf["awaiting_human_review"] and [p["vendor_id"] for p in wf["pending_review"]] == [ids["E"]]
    assert wf["workflow_status"] == "AWAITING_HUMAN_REVIEW"

    # human resolves E (original certificate says 3 April 2028); then the workflow resumes
    ereq = next(code for code, s_ in std.items() if s_ == "ISO 14001")
    r = c.post(f"/api/evaluations/{eid}/vendors/{ids['E']}/review", headers=REVIEWER_HEADERS,
               json={"requirement_code": ereq, "decision": "COMPLIANT", "reason": "Original shows expiry 3 April 2028 (day-first)"})
    assert r.json()["eligibility"] == exp["vendors"]["E"]["after_review"]["certification"]
    assert c.post(f"/api/evaluations/{eid}/workflow/resume", headers=REVIEWER_HEADERS).status_code == 202
    wf = c.get(f"/api/evaluations/{eid}/workflow").json()
    assert wf["workflow_status"] == "COMPLETED" and not wf["awaiting_human_review"]
    final = c.get(f"/api/evaluations/{eid}/results").json()
    by_id = {x["vendor_id"]: x for x in final["vendors"]}
    assert [by_id[i]["name"] for i in final["ranking"]] == names(system, exp["ranking_after_review"])
    assert by_id[ids["E"]]["technical"]["status"] == "QUALIFIED" and by_id[ids["E"]]["commercial"]["status"] == "VALID"
    for label in exp["never_downstream"]:
        assert by_id[ids[label]]["technical"]["status"] == "NOT_EVALUATED"
    assert not {f.vendor_id for f in db.query(CriterionFinding)} & {ids["B"], ids["D"]}

    # reports
    def sheet(kind, name):
        r = c.get(f"/api/evaluations/{eid}/reports/{kind}")
        assert r.status_code == 200
        ws = load_workbook(io.BytesIO(r.content))[name]
        rows = list(ws.iter_rows(values_only=True))
        return [dict(zip(rows[0], x)) for x in rows[1:]]
    cons = {r["Vendor"]: r for r in sheet("consolidated", "Final Comparison")}
    assert set(cons) == {e["name"] for e in exp["vendors"].values()}  # failed vendors still appear
    for label in exp["never_downstream"]:
        row = cons[exp["vendors"][label]["name"]]
        assert row["Technical"] == row["Commercial"] == "NOT_EVALUATED" and row["Rank"] is None
        assert "Certification failed" in row["Rejection / Pending Reason"]
    assert {r["Vendor"] for r in sheet("technical", "Technical Criteria")} == set(names(system, ["A", "C", "E"]))
    cert_vendors = {r["Vendor"]: r for r in sheet("certification", "Vendor Overview")}
    assert cert_vendors[exp["vendors"]["E"]["name"]]["Eligibility"] == "PASS"
    summary = {r["Vendor"]: r["Status"] for r in sheet("certification", "All Certifications") if r["Requirement ID"] == ereq}
    assert summary[exp["vendors"]["B"]["name"]] == "MISSING" and summary[exp["vendors"]["D"]["name"]] == "EXPIRED"


def test_every_generated_document_states_it_is_synthetic(dataset):
    import pypdfium2 as pdfium
    root, _ = dataset
    stamp = load_generator().STAMP
    pdfs = [root / "tender.pdf", *(p for p in (root / "vendors").rglob("*.pdf"))]
    checked = 0
    for p in pdfs:
        doc = pdfium.PdfDocument(str(p))
        for i in range(len(doc)):
            text = doc[i].get_textpage().get_text_bounded()
            if text.strip():  # scanned PDFs have no text layer; their image carries the stamp (checked via OCR above)
                assert stamp in text.replace("\r\n", "\n"), f"{p.name} page {i + 1} lacks the synthetic stamp"
                checked += 1
    import zipfile
    for z in (root / "vendors").rglob("*.zip"):  # ZIP members carry the stamp too
        with zipfile.ZipFile(z) as zf:
            for m in zf.namelist():
                path = root / f"_{z.stem}_{Path(m).name}"
                path.write_bytes(zf.read(m))
                assert stamp in pdfium.PdfDocument(str(path))[0].get_textpage().get_text_bounded().replace("\r\n", "\n"), m
                path.unlink()
                checked += 1
    assert checked >= 13 + 7  # tender (2 pages) + text PDFs + ZIP members
    assert "HAL" not in " ".join(p.read_bytes().decode("latin-1") for p in pdfs if p.name.startswith("tender"))  # never imitates HAL


def test_expected_results_file_is_self_consistent(dataset):
    _, exp = dataset
    assert set(exp["vendors"]) == set("ABCDE")
    assert {l for l, v in exp["vendors"].items() if v["certification"] == "PASS"} == {"A", "C"}
    assert exp["never_downstream"] == ["B", "D"] and exp["ranking_before_review"] == ["A", "C"]
    assert json.loads((dataset[0] / "expected_results.json").read_text("utf-8")) == json.loads(json.dumps(exp))
