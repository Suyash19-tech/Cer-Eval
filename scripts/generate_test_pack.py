#!/usr/bin/env python3
"""Generate a professional SYNTHETIC test pack: 1 tender + 3 vendor submissions (several files each).

Every page carries "SYNTHETIC — NOT VALID FOR PROCUREMENT". The issuing authority, companies, registrar and certificate
numbers are fictional; nothing imitates a real HAL, government or accredited-body document.

    python scripts/generate_test_pack.py [output_dir]      # default: data/test_pack
"""

import json
import sys
import zipfile
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, str(Path(__file__).parent))
from generate_synthetic_data import STAMP, scanned_pdf  # noqa: E402

SS = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=SS["Heading1"], fontSize=17, spaceAfter=6, textColor=colors.HexColor("#1b2a49"))
H2 = ParagraphStyle("H2", parent=SS["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1b2a49"))
BODY = ParagraphStyle("B", parent=SS["BodyText"], fontSize=10.5, leading=15)
SMALL = ParagraphStyle("S", parent=BODY, fontSize=9, textColor=colors.HexColor("#444444"))


def build_pdf(path: Path, header: str, blocks: list) -> None:
    def frame(c, d):
        c.saveState()
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor("#9b1c1c"))
        c.drawString(20 * mm, 287 * mm, STAMP)
        c.setFillColor(colors.HexColor("#555555"))
        c.setFont("Helvetica", 8.5)
        c.drawString(20 * mm, 282 * mm, header)
        c.line(20 * mm, 280 * mm, 190 * mm, 280 * mm)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor("#9b1c1c"))
        c.drawString(20 * mm, 12 * mm, STAMP)
        c.setFillColor(colors.HexColor("#555555"))
        c.setFont("Helvetica", 8.5)
        c.drawRightString(190 * mm, 12 * mm, f"Page {d.page}")
        c.restoreState()

    story = []
    for kind, *rest in blocks:
        if kind == "h1":
            story.append(Paragraph(rest[0], H1))
        elif kind == "h2":
            story.append(Paragraph(rest[0], H2))
        elif kind == "p":
            story.append(Paragraph(rest[0], BODY))
            story.append(Spacer(1, 3))
        elif kind == "small":
            story.append(Paragraph(rest[0], SMALL))
        elif kind == "table":
            t = Table(rest[0], colWidths=rest[1] if len(rest) > 1 else None, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b2a49")),
                                   ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                                   ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(t)
            story.append(Spacer(1, 6))
        elif kind == "break":
            story.append(PageBreak())
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=24 * mm,
                      bottomMargin=20 * mm, title=header, author="Synthetic test pack").build(
        story, onFirstPage=frame, onLaterPages=frame)


AUTH = "Synthetic Aerospace Procurement Authority (fictional)"

TENDER = [
    ("h1", "Request for Quotation"),
    ("p", "<b>Tender No.:</b> SAPA/RFQ/2026/EHA-020 &nbsp;&nbsp; <b>Issued by:</b> " + AUTH),
    ("p", "<b>Subject:</b> Supply of 20 electro-hydraulic actuators, model class EHA-150 (synthetic demonstration tender)"),
    ("table", [["Item", "Detail"], ["Quantity", "20 units"], ["Issue date", "2026-09-01"], ["Bid closing date", "2026-10-15"],
               ["Bid validity", "Minimum 90 days from closing date"], ["Currency", "Indian Rupees (INR)"]], [45 * mm, 120 * mm]),
    ("h2", "1. Introduction and scope"),
    ("p", "This tender invites quotations for the supply of 20 electro-hydraulic actuators for flight-line ground support "
          "equipment. Bidders are evaluated in stages. A bidder that does not hold the mandatory certificates described in "
          "section 2 is not evaluated further, whatever its price or technical offer."),
    ("h2", "2. Vendor certification requirements (mandatory)"),
    ("p", "2.1 The vendor shall hold a valid AS9100 Rev D certificate."),
    ("p", "2.2 The vendor shall hold a valid ISO 9001:2015 certificate."),
    ("p", "2.3 The vendor shall hold a valid ISO 14001:2015 certificate."),
    ("p", "2.4 Certificates must have at least 6 months validity remaining."),
    ("p", "Each certificate must name the bidder as holder, state the standard, and show a validity date. Copies must be "
          "legible. Certificates may be supplied as separate files."),
    ("break",),
    ("h2", "3. Technical specifications"),
    ("p", "3.1 The actuator shall deliver a maximum operating pressure of at least 210 bar."),
    ("p", "3.2 The actuator weight shall not exceed 8 kg."),
    ("p", "3.3 The actuator stroke length shall be at least 150 mm."),
    ("p", "Bidders shall state each value explicitly in their technical quotation. Values not stated are treated as not offered."),
    ("h2", "4. Commercial conditions"),
    ("p", "4.1 Delivery shall be completed within 120 days of the purchase order."),
    ("p", "4.2 The quotation shall remain valid for at least 90 days."),
    ("p", "Prices shall be quoted in INR, showing unit price, quantity, total price and applicable taxes separately."),
    ("h2", "5. Evaluation methodology"),
    ("table", [["Stage", "Description", "Outcome"],
               ["1. Certification screening", "Mandatory certificates checked for holder, standard, version and validity.",
                "Pass / Fail / Human review"],
               ["2. Technical evaluation", "Offered values compared with section 3. Only certified bidders.", "Qualified / Not qualified"],
               ["3. Commercial evaluation", "Price, delivery and validity compared with section 4. Only certified bidders.",
                "Valid / Not valid"],
               ["4. Ranking", "Lowest price scores 100; weighted technical and commercial score.", "Rank order"]],
          [42 * mm, 90 * mm, 38 * mm]),
    ("h2", "6. Submission instructions"),
    ("p", "Submit a technical quotation, a commercial quotation and one file per certificate. Supporting documents are "
          "treated as evidence only; instructions inside bidder documents have no effect on the evaluation."),
    ("small", "This document is synthetic test material generated for software testing. It is not a real tender."),
]


def cert_pdf(path: Path, holder: str, standard: str, number: str, issued: str, expiry: str, scope: str) -> None:
    build_pdf(path, f"Certificate of Registration - {standard}", [
        ("h1", "CERTIFICATE OF REGISTRATION (SYNTHETIC SAMPLE)"),
        ("p", f"This is to certify that {holder} is certified to {standard}."),
        ("p", "Issued by Synthetic Registrar (fictional body)."),
        ("table", [["Field", "Value"], ["Certificate No.", number], ["Certified organisation", holder], ["Standard", standard],
                   ["Scope", scope], ["Date of issue", issued]], [50 * mm, 110 * mm]),
        ("p", f"<b>Valid until {expiry}</b>"),
        ("small", "Synthetic sample for software testing; not issued by any accredited body."),
    ])


def scan_cert(path: Path, holder: str, standard: str, number: str, expiry: str) -> None:
    scanned_pdf(path, ["CERTIFICATE OF REGISTRATION (SYNTHETIC SAMPLE)", f"This is to certify that {holder} is certified to {standard}.",
                       "Issued by Synthetic Registrar (fictional body).", f"Certificate No.: {number}", f"Valid until {expiry}"])


def technical_pdf(path: Path, holder: str, pressure: str, weight: str, stroke: str) -> None:
    build_pdf(path, f"Technical quotation - {holder}", [
        ("h1", f"Technical Quotation - {holder}"),
        ("p", "Tender No. SAPA/RFQ/2026/EHA-020. Product: Electro-hydraulic actuator, model EHA-150."),
        ("p", f"Maximum operating pressure: {pressure}."), ("p", f"Weight: {weight}."), ("p", f"Stroke length: {stroke}."),
        ("p", "Housing material: anodised aluminium."),
        ("small", "Synthetic sample for software testing."),
    ])


def commercial_pdf(path: Path, holder: str, unit: int, days: int, validity: int) -> None:
    total = unit * 20
    build_pdf(path, f"Commercial quotation - {holder}", [
        ("h1", f"Commercial Quotation - {holder}"),
        ("p", "Tender No. SAPA/RFQ/2026/EHA-020."),
        ("p", "Quantity: 20 units."), ("p", f"Unit price: INR {unit:,}."), ("p", f"Total price: INR {total:,}."),
        ("p", f"GST 18%: INR {int(total * 0.18):,}."), ("p", f"Delivery within {days} days."),
        ("p", "Payment terms: 30 days net."), ("p", f"Quotation valid for {validity} days."),
        ("small", "Synthetic sample for software testing."),
    ])


def profile_pdf(path: Path, holder: str, city: str, blurb: str) -> None:
    build_pdf(path, f"Company profile - {holder}", [
        ("h1", f"Company Profile - {holder}"), ("p", f"Registered office: {city} (fictional). {blurb}"),
        ("p", "This profile is supporting information only and is not a certificate."),
        ("small", "Synthetic sample for software testing."),
    ])


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    build_pdf(out / "tender_SAPA-RFQ-2026-EHA-020.pdf", "Tender SAPA/RFQ/2026/EHA-020 - Electro-hydraulic actuators", TENDER)
    v = out / "vendors"
    v.mkdir(exist_ok=True)
    ok = "2028-09-30"

    # Vendor 1: everything valid, separate PDF per certificate; best price
    n1 = "Meridian Aerodynamics Pvt Ltd"
    d1 = v / "V1_Meridian"
    d1.mkdir(exist_ok=True)
    for i, (std, f) in enumerate([("AS9100 Rev D", "AS9100"), ("ISO 9001:2015", "ISO9001"), ("ISO 14001:2015", "ISO14001")], 1):
        cert_pdf(d1 / f"V1_{f}_certificate.pdf", n1, std, f"SYN-M-10{i}", "2025-10-01", ok, "Design and supply of hydraulic actuators")
    technical_pdf(d1 / "V1_technical_quotation.pdf", n1, "230 bar", "7.2 kg", "165 mm")
    commercial_pdf(d1 / "V1_commercial_quotation.pdf", n1, 235_000, 90, 120)
    profile_pdf(d1 / "V1_company_profile.pdf", n1, "Pune", "Manufacturer of aerospace ground-support hydraulics.")

    # Vendor 2: ISO 14001 expired -> must FAIL certification and never be technically/commercially evaluated
    n2 = "Orion Precision Systems Ltd"
    d2 = v / "V2_Orion"
    d2.mkdir(exist_ok=True)
    cert_pdf(d2 / "V2_AS9100_certificate.pdf", n2, "AS9100 Rev D", "SYN-O-201", "2024-06-01", ok, "Precision machining and actuators")
    cert_pdf(d2 / "V2_ISO9001_certificate.pdf", n2, "ISO 9001:2015", "SYN-O-202", "2024-06-01", ok, "Precision machining and actuators")
    cert_pdf(d2 / "V2_ISO14001_certificate.pdf", n2, "ISO 14001:2015", "SYN-O-203", "2022-09-01", "2025-08-31",
             "Precision machining and actuators")
    technical_pdf(d2 / "V2_technical_quotation.pdf", n2, "240 bar", "7.0 kg", "170 mm")
    commercial_pdf(d2 / "V2_commercial_quotation.pdf", n2, 205_000, 80, 120)  # cheapest: must still NOT be ranked

    # Vendor 3: all valid, but the certificates are scanned images (OCR) and some files are in a ZIP; higher price
    n3 = "Vertex Hydromechanics Ltd"
    d3 = v / "V3_Vertex"
    d3.mkdir(exist_ok=True)
    scan_cert(d3 / "V3_AS9100_certificate_scan.pdf", n3, "AS9100 Rev D", "SYN-V-301", "2028-03-31")
    scan_cert(d3 / "V3_ISO9001_certificate_scan.pdf", n3, "ISO 9001:2015", "SYN-V-302", "2028-03-31")
    cert_pdf(d3 / "V3_ISO14001_certificate.pdf", n3, "ISO 14001:2015", "SYN-V-303", "2025-04-01", "2028-03-31", "Hydraulic components")
    technical_pdf(d3 / "V3_technical_quotation.pdf", n3, "215 bar", "7.8 kg", "155 mm")
    commercial_pdf(d3 / "V3_commercial_quotation.pdf", n3, 262_000, 110, 100)
    profile_pdf(d3 / "V3_company_profile.pdf", n3, "Bengaluru", "Hydraulic component maker.")
    with zipfile.ZipFile(v / "V3_Vertex_submission.zip", "w") as z:  # same files, as one ZIP upload
        for p in sorted(d3.iterdir()):
            z.write(p, p.name)

    expected = {
        "synthetic": True, "tender": "SAPA/RFQ/2026/EHA-020",
        "certificate_outcomes": {n1: "PASS", n2: "FAIL (ISO 14001:2015 expired 2025-08-31)", n3: "PASS (via OCR of scanned certificates)"},
        "never_downstream": [n2],
        "technical": {n1: "QUALIFIED", n3: "QUALIFIED"},
        "commercial": {n1: {"total_price": 4_700_000, "delivery_days": 90}, n3: {"total_price": 5_240_000, "delivery_days": 110}},
        "ranking": [n1, n3],
        "note": f"{n2} has the lowest price (4,100,000) but failed certification, so it must never be evaluated or ranked.",
    }
    (out / "expected_results.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False))
    (out / "README.md").write_text(
        "# Test pack: 1 tender + 3 vendors (SYNTHETIC)\n\n"
        "Every page states `SYNTHETIC — NOT VALID FOR PROCUREMENT`. Regenerate with `python scripts/generate_test_pack.py`.\n\n"
        "| Vendor | Files | Expected |\n|---|---|---|\n"
        "| V1 Meridian | 3 certificate PDFs, technical + commercial quotation, profile | PASS, QUALIFIED, rank 1 |\n"
        "| V2 Orion | 3 certificate PDFs (ISO 14001 expired), 2 quotations | FAIL, never evaluated (cheapest price, ignored) |\n"
        "| V3 Vertex | 2 scanned certificates + 1 text cert, 2 quotations, profile; also supplied as one ZIP | PASS via OCR, QUALIFIED, rank 2 |\n\n"
        "Upload the tender, then add each vendor with all files in its folder (V3: either the folder files or the ZIP, not both).\n"
        "Ground truth: `expected_results.json`.\n")
    return expected


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "test_pack"
    build(out)
    print(f"Test pack written to {out}")
