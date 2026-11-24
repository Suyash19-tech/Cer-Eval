#!/usr/bin/env python3
"""Generate the SYNTHETIC five-vendor demonstration dataset and its expected results.

Every generated page states "SYNTHETIC - NOT VALID FOR PROCUREMENT". Company names, registrar and certificate numbers are
fictional; nothing imitates a real HAL-issued, government or accredited-body document. The dataset is for the explicitly
marked demonstration/test environment only and must never be mixed into real evaluations.

    python scripts/generate_synthetic_data.py [output_dir]      # default: data/synthetic
"""

import json
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

STAMP = "SYNTHETIC — NOT VALID FOR PROCUREMENT"
_FONTS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for f in _FONTS:
        if Path(f).is_file():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def pdf(path: Path, pages: list[list[str]]) -> None:
    """Text PDF; the synthetic stamp is on the top and bottom of every page."""
    c = canvas.Canvas(str(path))
    for lines in pages:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, 810, STAMP)
        c.setFont("Helvetica", 11)
        y = 780
        for line in lines:
            c.drawString(40, y, line)
            y -= 18
        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, 30, STAMP)
        c.showPage()
    c.save()


def render_image(lines: list[str], size: int = 34, noise: bool = True) -> Image.Image:
    font = _font(size)
    stamp_font = _font(size - 6)
    img = Image.new("L", (1700, 220 + 62 * len(lines)), 255)
    d = ImageDraw.Draw(img)
    d.text((50, 30), STAMP, fill=0, font=stamp_font)
    y = 120
    for line in lines:
        d.text((50, y), line, fill=0, font=font)
        y += 62
    d.text((50, y + 20), STAMP, fill=0, font=stamp_font)
    if noise:  # mild scan-like softening; keeps the text OCR-readable
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img.convert("RGB")


def scanned_pdf(path: Path, lines: list[str]) -> None:
    """Image-only PDF: no text layer, so OCR is required."""
    img = render_image(lines)
    png = path.with_suffix(".tmp.png")
    img.save(png)
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    w = 515
    c.drawImage(ImageReader(str(png)), 40, 842 - 40 - w * img.height / img.width, width=w, height=w * img.height / img.width)
    c.showPage()
    c.save()
    png.unlink()


def cert_lines(holder: str, standard: str, expiry: str, number: str) -> list[str]:
    return ["CERTIFICATE OF REGISTRATION (SYNTHETIC SAMPLE)",
            f"This is to certify that {holder} is certified to {standard}.",
            "Issued by Synthetic Registrar (fictional body).",
            f"Certificate No.: {number}",
            f"Valid until {expiry}"]


def tech_lines(holder: str, pressure: str, weight: str) -> list[str]:
    return [f"Technical quotation and technical compliance statement - {holder}",
            "Product: Hydraulic pump, model SYN-HP-250.",
            f"Maximum operating pressure: {pressure}.", f"Weight: {weight}.",
            "Housing material: stainless steel."]


def comm_lines(holder: str, unit: int, days: int) -> list[str]:
    return [f"Commercial quotation - {holder}", "Quantity: 10 units.", f"Unit price: INR {unit:,}.",
            f"Total price: INR {unit * 10:,}.", f"GST 18%: INR {int(unit * 10 * 0.18):,}.", f"Delivery within {days} days.",
            "Payment terms: 30 days net.", "Quotation valid for 90 days."]


TENDER_PAGES = [
    ["Tender No. SYN-2026-001: Supply of 10 hydraulic pumps (synthetic demonstration tender)", "",
     "1. Vendor certification requirements",
     "1.1 Category X: The vendor shall hold a valid AS9100 Rev D certificate.",
     "1.2 Category Y: The vendor shall hold a valid ISO 14001:2015 certificate.",
     "1.3 Certificates must have at least 6 months validity remaining."],
    ["2. Technical specifications",
     "2.1 The pump shall deliver a maximum operating pressure of at least 250 bar.",
     "2.2 The pump weight shall not exceed 15 kg.", "",
     "3. Commercial conditions",
     "3.1 Delivery shall be completed within 90 days of the purchase order.",
     "3.2 The quotation shall remain valid for at least 60 days."],
]

OK = "2028-06-30"


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    vend = out / "vendors"
    vend.mkdir(exist_ok=True)
    pdf(out / "tender.pdf", TENDER_PAGES)
    names = {"A": "Alpha Aerospace Pvt Ltd", "B": "Beta Precision Works Ltd", "C": "Gamma Hydraulics Ltd",
             "D": "Delta Fluid Systems Ltd", "E": "Echo Engineering Ltd"}
    price = {"A": 100_000, "B": 92_000, "C": 115_000, "D": 98_000, "E": 108_000}
    pressure = {"A": "275 bar", "B": "280 bar", "C": "262 bar", "D": "270 bar", "E": "255 bar"}
    weight = {"A": "12 kg", "B": "11 kg", "C": "14 kg", "D": "13 kg", "E": "13.5 kg"}
    days = {"A": 60, "B": 55, "C": 75, "D": 65, "E": 80}

    def d(k: str) -> Path:
        p = vend / k
        p.mkdir(exist_ok=True)
        return p

    def quotes(k: str, folder: Path) -> None:
        pdf(folder / f"{k}_technical_quotation.pdf", [tech_lines(names[k], pressure[k], weight[k])])
        pdf(folder / f"{k}_commercial_quotation.pdf", [comm_lines(names[k], price[k], days[k])])

    # A: all valid; plain text PDFs
    f = d("A")
    pdf(f / "A_AS9100_certificate.pdf", [cert_lines(names["A"], "AS9100 Rev D", OK, "SYN-A-0001")])
    pdf(f / "A_ISO14001_certificate.pdf", [cert_lines(names["A"], "ISO 14001:2015", OK, "SYN-A-0002")])
    quotes("A", f)
    # B: ISO 14001 missing; delivered as a ZIP archive
    f = d("B")
    stage = f / "_stage"
    stage.mkdir(exist_ok=True)
    pdf(stage / "B_AS9100_certificate.pdf", [cert_lines(names["B"], "AS9100 Rev D", OK, "SYN-B-0001")])
    quotes("B", stage)
    with zipfile.ZipFile(f / "B_submission.zip", "w") as z:
        for p in sorted(stage.iterdir()):
            z.write(p, f"documents/{p.name}")
            p.unlink()
    stage.rmdir()
    # C: all valid; scanned (image-only) PDF + image certificate + supporting document
    f = d("C")
    scanned_pdf(f / "C_AS9100_certificate_scan.pdf", cert_lines(names["C"], "AS9100 Rev D", OK, "SYN-C-0001"))
    render_image(cert_lines(names["C"], "ISO 14001:2015", OK, "SYN-C-0002")).save(f / "C_ISO14001_certificate.png")
    pdf(f / "C_company_profile.pdf", [["Company profile and declaration - " + names["C"], "Annexure: general company information."]])
    quotes("C", f)
    # D: ISO 14001 expired
    f = d("D")
    pdf(f / "D_AS9100_certificate.pdf", [cert_lines(names["D"], "AS9100 Rev D", OK, "SYN-D-0001")])
    pdf(f / "D_ISO14001_certificate.pdf", [cert_lines(names["D"], "ISO 14001:2015", "2025-03-01", "SYN-D-0002")])
    quotes("D", f)
    # E: ambiguous day/month date on the ISO certificate; ZIP submission
    f = d("E")
    stage = f / "_stage"
    stage.mkdir(exist_ok=True)
    pdf(stage / "E_AS9100_certificate.pdf", [cert_lines(names["E"], "AS9100 Rev D", OK, "SYN-E-0001")])
    pdf(stage / "E_ISO14001_certificate.pdf", [cert_lines(names["E"], "ISO 14001:2015", "03/04/2028", "SYN-E-0002")])
    quotes("E", stage)
    with zipfile.ZipFile(f / "E_submission.zip", "w") as z:
        for p in sorted(stage.iterdir()):
            z.write(p, p.name)
            p.unlink()
    stage.rmdir()

    def vendor(k: str, cert: str, findings: dict, **kw) -> dict:
        return {"label": k, "name": names[k], "certification": cert, "findings": findings, "total_price": price[k] * 10, **kw}

    expected = {
        "_note": "Ground truth written by the generator, independent of the system under test. SYNTHETIC data.",
        "as_of": "2026-11-23",
        "tender_requirements": [
            {"standard": "AS9100", "version": "D", "category": "X", "mandatory": True},
            {"standard": "ISO 14001", "version": "2015", "category": "Y", "mandatory": True}],
        "tender_criteria": {"technical": ["maximum operating pressure >= 250 bar", "weight <= 15 kg"],
                            "commercial": ["delivery <= 90 days", "quotation validity >= 60 days"]},
        "vendors": {
            "A": vendor("A", "PASS", {"AS9100": "COMPLIANT", "ISO 14001": "COMPLIANT"}, downstream=True,
                        technical="QUALIFIED", commercial="VALID"),
            "B": vendor("B", "FAIL", {"AS9100": "COMPLIANT", "ISO 14001": "MISSING"}, downstream=False),
            "C": vendor("C", "PASS", {"AS9100": "COMPLIANT", "ISO 14001": "COMPLIANT"}, downstream=True,
                        technical="QUALIFIED", commercial="VALID", needs_ocr=True),
            "D": vendor("D", "FAIL", {"AS9100": "COMPLIANT", "ISO 14001": "EXPIRED"}, downstream=False),
            "E": vendor("E", "PENDING_HUMAN_REVIEW", {"AS9100": "COMPLIANT", "ISO 14001": "NEEDS_HUMAN_REVIEW"}, downstream=False,
                        after_review={"certification": "PASS", "downstream": True, "technical": "QUALIFIED", "commercial": "VALID"}),
        },
        "never_downstream": ["B", "D"],
        "ranking_before_review": ["A", "C"],
        "ranking_after_review": ["A", "E", "C"],
    }
    (out / "expected_results.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False), "utf-8")
    return expected


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "synthetic"
    build(target)
    print(f"Synthetic dataset written to {target}")
