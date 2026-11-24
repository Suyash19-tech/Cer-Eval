import zipfile

from tests.test_document_processing import make_pdf
from tests.test_screening import add_vendor, cert, setup  # noqa: F401


def test_evaluation_list_and_vendor_list(client, setup, tmp_path):
    add_vendor(client, tmp_path, setup, "Alpha", [cert("Alpha Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                                                  cert("Alpha Ltd", "ISO 14001:2015", "Valid until 2028-06-30")])
    add_vendor(client, tmp_path, setup, "Beta", [cert("Beta Ltd", "AS9100 Rev D", "Valid until 2028-06-30")])
    rows = client.get("/api/evaluations").json()
    assert rows[0]["id"] == setup and (rows[0]["vendors"], rows[0]["pass"], rows[0]["fail"], rows[0]["pending"]) == (2, 1, 1, 0)
    vs = client.get(f"/api/evaluations/{setup}/vendors").json()
    assert [v["name"] for v in vs] == ["Alpha", "Beta"] and vs[0]["findings"] and vs[0]["documents"]
    assert client.get("/api/evaluations/nope/vendors").status_code == 404


def test_original_document_download_is_vendor_scoped(client, setup, tmp_path):
    a = add_vendor(client, tmp_path, setup, "Alpha", [cert("Alpha Ltd", "AS9100 Rev D", "Valid until 2028-06-30")])
    b = add_vendor(client, tmp_path, setup, "Beta", [cert("Beta Ltd", "AS9100 Rev D", "Valid until 2028-06-30")])
    da = a["documents"][0]["id"]
    r = client.get(f"/api/evaluations/{setup}/vendors/{a['id']}/documents/{da}/file")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"] == "application/pdf"
    # another vendor's id cannot be used to read it, nor a made-up document id
    assert client.get(f"/api/evaluations/{setup}/vendors/{b['id']}/documents/{da}/file").status_code == 404
    assert client.get(f"/api/evaluations/{setup}/vendors/{a['id']}/documents/nope/file").status_code == 404


def test_zip_member_download(client, setup, tmp_path):
    p = make_pdf(tmp_path / "in.pdf", cert("Zed Ltd", "AS9100 Rev D", "Valid until 2028-06-30"))
    z = tmp_path / "sub.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(p, "certs/as9100.pdf")
    r = client.post(f"/api/evaluations/{setup}/vendors", data={"name": "Zed"},
                    files=[("files", ("sub.zip", z.read_bytes(), "application/zip"))])
    assert r.status_code == 201
    v = r.json()
    d = client.get(f"/api/evaluations/{setup}/vendors/{v['id']}/documents/{v['documents'][0]['id']}/file")
    assert d.status_code == 200 and d.content.startswith(b"%PDF")


def test_evaluation_details_only_has_qualified_vendors(client, setup):
    r = client.get(f"/api/evaluations/{setup}/evaluation-details")
    assert r.status_code == 200 and r.json() == {"findings": [], "commercial": []}
    assert client.get("/api/evaluations/nope/evaluation-details").status_code == 404
