import threading
from datetime import datetime, timezone

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_rag, get_workflow_graph
from app.database.session import Base
from app.graph.state import StateConflictError, merge_vendor_results
from app.graph.workflow import WorkflowDeps, build_workflow
from app.models import CertificateFinding, Evaluation, Vendor
from app.services import vendor_service
from app.schemas.enums import ValidationStatus
from tests.conftest import REVIEWER_HEADERS
from tests.test_screening import CertLLM, add_vendor, cert, setup  # noqa: F401
from tests.test_rag import HashEmbedder  # noqa: F401


def seen_log(rec):
    def fn(db, eid, vid):
        rec.append(vid)
        return {"status": "EVALUATED", "vendor": vid}
    return fn


@pytest.fixture
def wf(client, engine, setup, tmp_path, monkeypatch):  # noqa: F811
    """Real screening (scripted LLM, hash embedder) wrapped in the real graph with an in-memory checkpointer."""
    from app.api.dependencies import get_rag
    from app.services import workflow_service
    # the API tests share ONE in-memory sqlite connection; real parallelism is tested separately on a file database
    monkeypatch.setattr(workflow_service, "MAX_CONCURRENCY", 1)
    rag = client.app.dependency_overrides[get_rag]()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    tech, comm = [], []
    deps = WorkflowDeps(session_factory=factory, llm=CertLLM(), rag=rag, reports_dir=tmp_path / "reports",
                        technical=seen_log(tech), commercial=seen_log(comm))
    graph = build_workflow(deps, MemorySaver())
    client.app.dependency_overrides[get_workflow_graph] = lambda: graph
    return {"eid": setup, "tech": tech, "comm": comm, "graph": graph, "tmp": tmp_path, "factory": factory}


def five_vendors(client, wf):
    eid, tmp = wf["eid"], wf["tmp"]
    ids = {}
    def mk(name, pdfs):
        from tests.test_document_processing import make_pdf
        files = []
        for i, pages in enumerate(pdfs):
            p = make_pdf(tmp / f"{name}{i}.pdf", pages)
            files.append(("files", (p.name, p.read_bytes(), "application/pdf")))
        r = client.post(f"/api/evaluations/{eid}/vendors", data={"name": name}, files=files)
        assert r.status_code == 201
        ids[name] = r.json()["id"]
    ok = lambda h, std, exp="Valid until 2028-06-30": cert(h, std, exp)  # noqa: E731
    mk("Alpha", [ok("Alpha Ltd", "AS9100 Rev D"), ok("Alpha Ltd", "ISO 14001:2015")])
    mk("Beta", [ok("Beta Ltd", "AS9100 Rev D")])
    mk("Gamma", [ok("Gamma Ltd", "AS9100 Rev D"), ok("Gamma Ltd", "ISO 14001:2015")])
    mk("Delta", [ok("Delta Ltd", "AS9100 Rev D"), ok("Delta Ltd", "ISO 14001:2015", "Valid until 2025-03-01")])
    mk("Echo", [ok("Echo Ltd", "AS9100 Rev D"), ok("Echo Ltd", "ISO 14001:2015", "Valid until 03/04/2028")])
    return ids


def start(client, eid):
    r = client.post(f"/api/evaluations/{eid}/workflow/start?as_of=2026-11-23")
    assert r.status_code == 202, r.text
    return client.get(f"/api/evaluations/{eid}/workflow").json()


def test_gate_routes_only_passing_vendors_downstream(client, wf):
    ids = five_vendors(client, wf)
    s = start(client, wf["eid"])
    elig = {v: r["screening"]["eligibility"] for v, r in s["vendor_results"].items()}
    assert elig == {ids["Alpha"]: "PASS", ids["Beta"]: "FAIL", ids["Gamma"]: "PASS", ids["Delta"]: "FAIL",
                    ids["Echo"]: "PENDING_HUMAN_REVIEW"}
    assert sorted(wf["tech"]) == sorted([ids["Alpha"], ids["Gamma"]]) == sorted(wf["comm"])  # FAIL/PENDING never reach it
    assert set(s["downstream_done"]) == {ids["Alpha"], ids["Gamma"]}
    for v in (ids["Beta"], ids["Delta"], ids["Echo"]):
        assert "technical" not in s["vendor_results"][v] and "commercial" not in s["vendor_results"][v]
    assert s["awaiting_human_review"] and s["pending_review"][0]["vendor_id"] == ids["Echo"]
    assert s["workflow_status"] == "AWAITING_HUMAN_REVIEW"
    # report exists before any downstream evaluation (log order)
    order = [e["node"] for e in s["node_log"]]
    assert order.index("generate_certification_report") < order.index("technical_evaluation")
    assert len(s["certification_reports"]) == 1


def test_start_twice_conflicts(client, wf):
    five_vendors(client, wf)
    start(client, wf["eid"])
    assert client.post(f"/api/evaluations/{wf['eid']}/workflow/start").status_code == 409


def test_resume_requires_reviewer_and_waiting_state(client, wf):
    five_vendors(client, wf)
    eid = wf["eid"]
    assert client.post(f"/api/evaluations/{eid}/workflow/resume").status_code == 401
    assert client.post(f"/api/evaluations/{eid}/workflow/resume", headers=REVIEWER_HEADERS).status_code == 409  # not started
    start(client, eid)
    assert client.post(f"/api/evaluations/{eid}/workflow/resume", headers={"X-Reviewer-Token": "x"}).status_code == 403


def test_resume_without_review_keeps_vendor_pending(client, wf):
    ids = five_vendors(client, wf)
    eid = wf["eid"]
    start(client, eid)
    assert client.post(f"/api/evaluations/{eid}/workflow/resume", headers=REVIEWER_HEADERS).status_code == 202
    s = client.get(f"/api/evaluations/{eid}/workflow").json()
    assert s["awaiting_human_review"] and ids["Echo"] not in wf["tech"]  # pending is never coerced to PASS


def test_approved_review_then_resume_sends_vendor_downstream(client, wf):
    ids = five_vendors(client, wf)
    eid = wf["eid"]
    start(client, eid)
    r = client.post(f"/api/evaluations/{eid}/vendors/{ids['Echo']}/review", headers=REVIEWER_HEADERS,
                    json={"requirement_code": "REQ-OTH-001", "decision": "COMPLIANT", "reason": "Verified original: 3 April 2028"})
    assert r.json()["eligibility"] == "PASS"
    assert ids["Echo"] not in wf["tech"]  # nothing happens until the workflow is resumed
    client.post(f"/api/evaluations/{eid}/workflow/resume", headers=REVIEWER_HEADERS)
    s = client.get(f"/api/evaluations/{eid}/workflow").json()
    assert s["workflow_status"] == "COMPLETED" and not s["awaiting_human_review"]
    assert sorted(wf["tech"]) == sorted([ids["Alpha"], ids["Gamma"], ids["Echo"]])
    assert len(s["certification_reports"]) == 2  # regenerated after review
    assert any(e["node"] == "human_review" and e["resumed_by"] == "alice" for e in s["node_log"])


def test_rejected_review_ends_vendor(client, wf):
    ids = five_vendors(client, wf)
    eid = wf["eid"]
    start(client, eid)
    client.post(f"/api/evaluations/{eid}/vendors/{ids['Echo']}/review", headers=REVIEWER_HEADERS,
                json={"requirement_code": "REQ-OTH-001", "decision": "EXPIRED", "reason": "Original shows expiry 2025"})
    client.post(f"/api/evaluations/{eid}/workflow/resume", headers=REVIEWER_HEADERS)
    s = client.get(f"/api/evaluations/{eid}/workflow").json()
    assert s["workflow_status"] == "COMPLETED" and s["vendor_results"][ids["Echo"]]["screening"]["eligibility"] == "FAIL"
    assert ids["Echo"] not in wf["tech"]


def test_unconfirmed_requirements_cannot_start(client, wf, db_session):
    five_vendors(client, wf)
    ev = db_session.get(Evaluation, wf["eid"])
    ev.requirements_confirmed_at = None
    db_session.commit()
    client.post(f"/api/evaluations/{wf['eid']}/workflow/start")
    db_session.expire_all()  # the workflow recorded the failure through its own session
    s = client.get(f"/api/evaluations/{wf['eid']}/workflow").json()
    assert s["workflow_status"] == "FAILED" and "not confirmed" in s["error"] and not wf["tech"]


def test_reducer_rejects_conflicting_downstream_result():
    a = merge_vendor_results({}, {"v1": {"technical": {"score": 1}}})
    assert merge_vendor_results(a, {"v1": {"technical": {"score": 1}}}) == a
    with pytest.raises(StateConflictError):
        merge_vendor_results(a, {"v1": {"technical": {"score": 2}}})
    out = merge_vendor_results(a, {"v1": {"screening": {"e": "PASS"}}, "v2": {"screening": {"e": "FAIL"}}})
    assert set(out) == {"v1", "v2"} and out["v1"]["technical"] == {"score": 1}  # vendors never overwrite each other


# ---- parallelism and persistence with a file database and a stub screener ----------------------
def make_env(tmp_path, n, checkpointer, screen):
    engine = create_engine(f"sqlite:///{tmp_path/'wf.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    if not db.query(Evaluation).count():
        ev = Evaluation(name="E", tender_path="x", tender_sha256="0" * 64, requirements_confirmed_at=datetime.now(timezone.utc))
        db.add(ev)
        db.flush()
        for i in range(n):
            db.add(Vendor(evaluation_id=ev.id, name=f"V{i}"))
        db.commit()
    eid = db.query(Evaluation).first().id
    vids = [v.id for v in db.query(Vendor).order_by(Vendor.name)]
    db.close()
    rec = []
    deps = WorkflowDeps(session_factory=factory, llm=None, rag=None, reports_dir=tmp_path / "rep", screen_fn=screen,
                        technical=seen_log(rec), commercial=seen_log(rec))
    return build_workflow(deps, checkpointer), eid, vids, factory, rec


def stub_screen(outcomes, barrier=None):
    def fn(factory, llm, rag, eid, vid, as_of):
        if barrier:
            barrier.wait(timeout=10)  # raises BrokenBarrierError unless all vendors are screened concurrently
        db = factory()
        v = db.get(Vendor, vid)
        v.eligibility, v.screening_status, v.eligibility_reason = outcomes[v.name], "DONE", "stub"
        if outcomes[v.name] == "PENDING_HUMAN_REVIEW":
            db.add(CertificateFinding(evaluation_id=eid, vendor_id=vid, requirement_code="R1", mandatory=True,
                                      status="NEEDS_HUMAN_REVIEW", reasons=["x"], evidence={}))
        db.commit()
        db.close()
    return fn


def test_vendors_are_screened_in_parallel(tmp_path):
    barrier = threading.Barrier(3)
    g, eid, vids, _, rec = make_env(tmp_path, 3, MemorySaver(), stub_screen(
        {"V0": "PASS", "V1": "FAIL", "V2": "PASS"}, barrier))
    out = g.invoke({"evaluation_id": eid, "as_of": None}, {"configurable": {"thread_id": eid}, "max_concurrency": 4})
    assert out["status"] == "COMPLETED" and sorted(rec) == sorted([vids[0], vids[0], vids[2], vids[2]])


def test_checkpoint_survives_restart(tmp_path):
    import sqlite3
    path = tmp_path / "cp.sqlite"
    outcomes = {"V0": "PASS", "V1": "PENDING_HUMAN_REVIEW"}
    g1, eid, vids, factory, rec = make_env(tmp_path, 2, SqliteSaver(sqlite3.connect(path, check_same_thread=False)),
                                           stub_screen(outcomes))
    cfg = {"configurable": {"thread_id": eid}}
    g1.invoke({"evaluation_id": eid, "as_of": None}, cfg)
    assert g1.get_state(cfg).next == ("human_review",)
    # "restart": brand-new graph + connection on the same files
    g2, _, _, _, rec2 = make_env(tmp_path, 2, SqliteSaver(sqlite3.connect(path, check_same_thread=False)), stub_screen(outcomes))
    assert g2.get_state(cfg).next == ("human_review",)
    db = factory()
    vendor_service.review_finding(db, eid, vids[1], "alice", "R1", ValidationStatus.COMPLIANT, "checked the original")
    db.commit()
    db.close()
    from langgraph.types import Command
    out = g2.invoke(Command(resume={"reviewer": "alice"}), cfg)
    assert out["status"] == "COMPLETED" and set(out["downstream_done"]) == {vids[0], vids[1]}


def test_failed_node_can_be_retried_from_checkpoint(client, wf):
    ids = five_vendors(client, wf)
    eid = wf["eid"]
    calls = {"n": 0}
    real = wf["graph"]  # same graph object; make the technical evaluator fail once
    orig_tech = wf["tech"]

    def flaky(db, e, v):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model crashed mid-evaluation")
        orig_tech.append(v)
        return {"status": "EVALUATED"}
    # rebuild the graph with the flaky evaluator but the same checkpointer
    from app.graph.workflow import WorkflowDeps as D
    deps = D(session_factory=wf["factory"], llm=CertLLM(), rag=client.app.dependency_overrides[get_rag](),
             reports_dir=wf["tmp"] / "reports", technical=flaky, commercial=seen_log(wf["comm"]))
    g = build_workflow(deps, real.checkpointer)
    client.app.dependency_overrides[get_workflow_graph] = lambda: g
    client.post(f"/api/evaluations/{eid}/workflow/start?as_of=2026-11-23")
    ev = client.get(f"/api/evaluations/{eid}/workflow").json()
    assert ev["workflow_status"] == "FAILED" and "model crashed" in ev["error"]
    url = f"/api/evaluations/{eid}/workflow/retry"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=REVIEWER_HEADERS).status_code == 202
    s = client.get(f"/api/evaluations/{eid}/workflow").json()
    assert s["awaiting_human_review"] and s["error"] is None  # got past the failure, now waiting for Echo's review
    assert sorted(set(wf["tech"])) == sorted([ids["Alpha"], ids["Gamma"]])
    assert client.post(url, headers=REVIEWER_HEADERS).status_code == 409  # nothing left to retry
