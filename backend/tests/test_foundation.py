import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.models import Document, Evaluation, Vendor


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["offline_mode"] is True


def test_reviewer_token_map_parsing():
    s = Settings(reviewer_tokens="alice:tok1, bob:tok2,bad")
    assert s.reviewer_token_map == {"tok1": "alice", "tok2": "bob"}
    assert Settings().reviewer_token_map == {}  # default: nobody authorised


def test_document_requires_vendor(db_session):
    ev = Evaluation(name="t", tender_path="x", tender_sha256="0" * 64)
    db_session.add(ev)
    db_session.flush()
    db_session.add(Document(evaluation_id=ev.id, vendor_id=None, filename="a", stored_path="a",
                            sha256="0", mime_type="application/pdf"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_vendor_document_roundtrip(db_session):
    ev = Evaluation(name="t", tender_path="x", tender_sha256="0" * 64)
    v = Vendor(name="Vendor A", evaluation=ev)
    db_session.add(ev)
    db_session.flush()
    v.documents.append(Document(evaluation_id=ev.id, filename="c.pdf", stored_path="p", sha256="1",
                                mime_type="application/pdf"))
    db_session.flush()
    assert db_session.get(Vendor, v.id).documents[0].document_class == "UNKNOWN"
