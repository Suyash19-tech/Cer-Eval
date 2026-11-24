import io

from openpyxl import load_workbook

from app.reporting.certification_report import safe
from tests.test_screening import add_vendor, cert, setup  # noqa: F401  (fixtures)

SHEETS = ["Executive Summary", "Vendor Overview", "X Certification Compliance", "Y Certification Compliance",
          "Z Certification Compliance", "All Certifications", "Missing Certificates", "Expired Certificates",
          "Mismatches", "Human Review Required", "Evidence References"]


def populate(client, tmp_path, eid):
    add_vendor(client, tmp_path, eid, "Alpha Aero", [cert("Alpha Aero Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                                                     cert("Alpha Aero Ltd", "ISO 14001:2015", "Valid until 2028-06-30")])
    add_vendor(client, tmp_path, eid, "Beta Works", [cert("Beta Works Ltd", "AS9100 Rev D", "Valid until 2028-06-30")])
    add_vendor(client, tmp_path, eid, "Delta Tech", [cert("Delta Tech Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                                                     cert("Delta Tech Ltd", "ISO 14001:2015", "Valid until 2025-03-01")])
    add_vendor(client, tmp_path, eid, "Echo Mfg", [cert("Echo Mfg Ltd", "AS9100 Rev D", "Valid until 2028-06-30"),
                                                   cert("Echo Mfg Ltd", "ISO 14001:2015", "Valid until 03/04/2028")])


def get_wb(client, eid):
    r = client.get(f"/api/evaluations/{eid}/reports/certification")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    return load_workbook(io.BytesIO(r.content))


def table(ws):
    rows = list(ws.iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:]]


def test_workbook_has_all_sheets_and_formatting(client, setup, tmp_path):
    populate(client, tmp_path, setup)
    wb = get_wb(client, setup)
    assert wb.sheetnames == SHEETS
    for name in SHEETS[1:]:
        ws = wb[name]
        assert ws.freeze_panes == "A2" and ws.auto_filter.ref and ws.column_dimensions["A"].width > 5
    assert wb["All Certifications"].conditional_formatting  # status colouring


def test_contents_match_findings(client, setup, tmp_path):
    populate(client, tmp_path, setup)
    wb = get_wb(client, setup)
    overview = {r["Vendor"]: r for r in table(wb["Vendor Overview"])}
    assert overview["Alpha Aero"]["Eligibility"] == "PASS"
    assert overview["Beta Works"]["Eligibility"] == "FAIL" and overview["Beta Works"]["Missing"] == 1
    assert overview["Delta Tech"]["Eligibility"] == "FAIL" and overview["Delta Tech"]["Expired"] == 1
    assert overview["Echo Mfg"]["Eligibility"] == "PENDING_HUMAN_REVIEW"
    assert [r["Vendor"] for r in table(wb["Missing Certificates"])] == ["Beta Works"]
    expired = table(wb["Expired Certificates"])
    assert [r["Vendor"] for r in expired] == ["Delta Tech"] and str(expired[0]["Expiry Date"]).startswith("2025-03-01")
    assert [r["Vendor"] for r in table(wb["Human Review Required"])] == ["Echo Mfg"]
    assert table(wb["Mismatches"]) == []
    x = table(wb["X Certification Compliance"])
    assert len(x) == 4 and all(r["Requirement ID"] == "REQ-X-001" for r in x)
    assert table(wb["Z Certification Compliance"]) == []
    ev = table(wb["Evidence References"])
    assert any(r["Vendor"] == "Alpha Aero" and r["Page"] == 1 and "AS9100" in r["Quoted Evidence"] for r in ev)
    summ = {r[0].value: r[1].value for r in wb["Executive Summary"].iter_rows(min_row=3) if r[0].value}
    assert (summ["PASS"], summ["FAIL"], summ["PENDING_HUMAN_REVIEW"], summ["Vendors"]) == (1, 2, 1, 4)


def test_unscreened_vendor_is_shown_as_not_screened(client, setup, tmp_path):
    from tests.test_document_processing import make_pdf
    p = make_pdf(tmp_path / "a.pdf", cert("Alpha Aero Ltd", "AS9100 Rev D", "Valid until 2028-06-30"))
    assert client.post(f"/api/evaluations/{setup}/vendors", data={"name": "Alpha"},
                       files=[("files", ("a.pdf", p.read_bytes(), "application/pdf"))]).status_code == 201
    wb = get_wb(client, setup)
    assert table(wb["Vendor Overview"])[0]["Eligibility"] == "NOT SCREENED"
    assert {r["Status"] for r in table(wb["All Certifications"])} == {"NOT SCREENED"}


def test_formula_injection_neutralised():
    assert safe("=HYPERLINK(\"http://evil\",\"x\")").startswith("'=")
    assert safe("+1+1").startswith("'+") and safe("@SUM(A1)").startswith("'@")
    assert safe("normal") == "normal" and safe(5) == 5 and safe("a\x00b") == "ab"


def test_malicious_vendor_name_is_not_a_formula(client, setup, tmp_path):
    add_vendor(client, tmp_path, setup, "=cmd|'/c calc'!A1", [cert("X Ltd", "AS9100 Rev D", "Valid until 2028-06-30")])
    wb = get_wb(client, setup)
    cell = wb["Vendor Overview"]["A2"]
    assert cell.data_type == "s" and cell.value.startswith("'=")


def test_unknown_evaluation_404(client):
    assert client.get("/api/evaluations/nope/reports/certification").status_code == 404
