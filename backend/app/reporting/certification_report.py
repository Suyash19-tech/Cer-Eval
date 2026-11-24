"""Certification compliance workbook (11 sheets). Reads persisted findings only; computes no statuses itself."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CertificateFinding, Document, Evaluation, TenderRequirement, Vendor
from app.schemas.enums import ValidationStatus as S

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
DATE_FMT = "yyyy-mm-dd"
FILLS = {
    "COMPLIANT": "C6EFCE", "PASS": "C6EFCE", "MISSING": "FFC7CE", "EXPIRED": "FFC7CE", "MISMATCH": "FFC7CE",
    "FAIL": "FFC7CE", "NEEDS_HUMAN_REVIEW": "FFEB9C", "PENDING_HUMAN_REVIEW": "FFEB9C", "NOT SCREENED": "D9D9D9",
}


def safe(value):  # noqa: ANN001, ANN201
    """Vendor-controlled text must never become an Excel formula (CSV/formula injection)."""
    if isinstance(value, str):
        value = "".join(ch for ch in value if ch >= " " or ch in "\n\t")
        if value[:1] in ("=", "+", "-", "@", "\t"):
            return "'" + value
    return value


@dataclass
class Row:
    vendor: Vendor
    req: TenderRequirement
    finding: CertificateFinding | None

    @property
    def status(self) -> str:
        return self.finding.status if self.finding else "NOT SCREENED"

    @property
    def ev(self) -> dict:
        return (self.finding.evidence if self.finding else None) or {}


def _load(db: Session, evaluation_id: str):  # noqa: ANN202
    ev = db.get(Evaluation, evaluation_id)
    vendors = list(db.scalars(select(Vendor).where(Vendor.evaluation_id == evaluation_id).order_by(Vendor.name)))
    reqs = list(db.scalars(select(TenderRequirement).where(
        TenderRequirement.evaluation_id == evaluation_id, TenderRequirement.confirmed.is_(True),
        TenderRequirement.rejected.is_(False)).order_by(TenderRequirement.requirement_code)))
    findings = {(f.vendor_id, f.requirement_code): f for f in db.scalars(
        select(CertificateFinding).where(CertificateFinding.evaluation_id == evaluation_id))}
    docs = list(db.scalars(select(Document).where(Document.evaluation_id == evaluation_id)))
    rows = [Row(v, r, findings.get((v.id, r.requirement_code))) for v in vendors for r in reqs]
    return ev, vendors, reqs, rows, docs


def _date(s: str | None):  # noqa: ANN202
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return s


class _Sheet:
    def __init__(self, wb: Workbook, title: str, headers: list[str], widths: list[int], first: bool = False) -> None:
        self.ws = wb.active if first else wb.create_sheet()
        self.ws.title = title
        self.headers = headers
        self.ws.append(headers)
        for i, w in enumerate(widths, 1):
            self.ws.column_dimensions[get_column_letter(i)].width = w
        for c in self.ws[1]:
            c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BORDER
            c.alignment = Alignment(wrap_text=True, vertical="center")
        self.ws.freeze_panes = "A2"

    def add(self, values: list) -> None:
        self.ws.append([safe(v) for v in values])
        for c in self.ws[self.ws.max_row]:
            c.border = BORDER
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if isinstance(c.value, (date, datetime)):
                c.number_format = DATE_FMT

    def finish(self, status_cols: list[str]) -> None:
        last = max(self.ws.max_row, 2)
        self.ws.auto_filter.ref = f"A1:{get_column_letter(len(self.headers))}{last}"
        for name in status_cols:
            col = get_column_letter(self.headers.index(name) + 1)
            rng = f"{col}2:{col}{last}"
            for label, color in FILLS.items():
                self.ws.conditional_formatting.add(
                    rng, CellIsRule(operator="equal", formula=[f'"{label}"'], fill=PatternFill("solid", bgColor=color, fgColor=color)))


CERT_HEADERS = ["Vendor", "Requirement ID", "Category", "Mandatory", "Certificate / Standard", "Required Version",
                "Status", "Reasons", "Holder", "Certificate No.", "Issuer", "Expiry Date", "Source Document", "Page"]
CERT_WIDTHS = [24, 14, 12, 10, 28, 12, 22, 50, 24, 16, 20, 13, 30, 7]


def _cert_row(r: Row) -> list:
    e = r.ev
    return [r.vendor.name, r.req.requirement_code, r.req.category, "Yes" if r.req.mandatory else "No",
            r.req.certificate_name or r.req.standard, r.req.version, r.status,
            "; ".join(r.finding.reasons or []) if r.finding else "Vendor not screened yet",
            e.get("holder_name"), e.get("certificate_number"), e.get("issuer"), _date(e.get("expiry_date")),
            e.get("document_name"), e.get("page_number")]


def build_workbook(db: Session, evaluation_id: str) -> Workbook:
    ev, vendors, reqs, rows, docs = _load(db, evaluation_id)
    wb = Workbook()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 1 Executive Summary
    ws = wb.active
    ws.title = "Executive Summary"
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 60
    ws["A1"], ws["A1"].font = safe(f"Certification Compliance Report - {ev.name}"), Font(bold=True, size=14)
    elig = [v.eligibility or "NOT SCREENED" for v in vendors]
    summary = [
        ("Evaluation ID", ev.id), ("Tender SHA-256", ev.tender_sha256), ("Generated", generated),
        ("Requirements confirmed by", ev.requirements_confirmed_by), ("Vendors", len(vendors)),
        ("PASS", elig.count("PASS")), ("FAIL", elig.count("FAIL")),
        ("PENDING_HUMAN_REVIEW", elig.count("PENDING_HUMAN_REVIEW")), ("Not screened", elig.count("NOT SCREENED")),
        ("Certification requirements evaluated", len(reqs)),
        ("Note", "Statuses are computed by deterministic validation; the LLM only proposes quoted evidence. "
                 "Only PASS vendors may proceed to technical and commercial evaluation."),
    ]
    for i, (k, v) in enumerate(summary, 3):
        ws.cell(i, 1, k).font = Font(bold=True)
        ws.cell(i, 2, safe(v)).alignment = Alignment(wrap_text=True, vertical="top")

    # 2 Vendor Overview
    s = _Sheet(wb, "Vendor Overview", ["Vendor", "Eligibility", "Reason", "Screening", "Documents", "Compliant", "Missing",
                                       "Expired", "Mismatch", "Needs Review"], [26, 24, 60, 14, 11, 11, 9, 9, 10, 13])
    for v in vendors:
        mine = [r for r in rows if r.vendor.id == v.id]
        cnt = lambda st: sum(1 for r in mine if r.status == st)  # noqa: E731
        s.add([v.name, v.eligibility or "NOT SCREENED", v.eligibility_reason, v.screening_status,
               sum(1 for d in docs if d.vendor_id == v.id), cnt("COMPLIANT"), cnt("MISSING"), cnt("EXPIRED"),
               cnt("MISMATCH"), cnt("NEEDS_HUMAN_REVIEW")])
    s.finish(["Eligibility"])

    # 3-5 X / Y / Z, 6 all
    for cat, title in (("X", "X Certification Compliance"), ("Y", "Y Certification Compliance"),
                       ("Z", "Z Certification Compliance")):
        s = _Sheet(wb, title, CERT_HEADERS, CERT_WIDTHS)
        for r in rows:
            if r.req.category == cat:
                s.add(_cert_row(r))
        s.finish(["Status"])
    s = _Sheet(wb, "All Certifications", CERT_HEADERS, CERT_WIDTHS)
    for r in rows:
        s.add(_cert_row(r))
    s.finish(["Status"])

    # 7-9 exception sheets
    for title, st in (("Missing Certificates", "MISSING"), ("Expired Certificates", "EXPIRED"), ("Mismatches", "MISMATCH")):
        s = _Sheet(wb, title, CERT_HEADERS, CERT_WIDTHS)
        for r in rows:
            if r.status == st:
                s.add(_cert_row(r))
        s.finish(["Status"])

    # 10 Human review
    s = _Sheet(wb, "Human Review Required", ["Vendor", "Requirement ID", "Mandatory", "Why review is needed",
                                             "Proposed evidence (quoted)", "Source Document", "Page", "Resolved By"],
               [24, 14, 10, 55, 60, 30, 7, 14])
    for r in rows:
        if r.status == "NEEDS_HUMAN_REVIEW":
            s.add([r.vendor.name, r.req.requirement_code, "Yes" if r.req.mandatory else "No",
                   "; ".join(r.finding.reasons or []), r.ev.get("supporting_text"), r.ev.get("document_name"),
                   r.ev.get("page_number"), r.finding.resolved_by])
    s.finish([])

    # 11 Evidence references
    s = _Sheet(wb, "Evidence References", ["Vendor", "Requirement ID", "Status", "Source Document", "Document ID", "Page",
                                           "Quoted Evidence", "Expiry Text", "Tender Source Page", "Tender Text"],
               [24, 14, 22, 30, 34, 7, 60, 30, 10, 60])
    for r in rows:
        if r.finding and r.ev:
            s.add([r.vendor.name, r.req.requirement_code, r.status, r.ev.get("document_name"), r.ev.get("document_id"),
                   r.ev.get("page_number"), r.ev.get("supporting_text"), r.ev.get("expiry_text"), r.req.source_page,
                   r.req.supporting_text])
    s.finish(["Status"])
    return wb


def write_report(db: Session, evaluation_id: str, reports_dir: Path) -> Path:
    wb = build_workbook(db, evaluation_id)
    out = reports_dir / evaluation_id
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"certification_compliance_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.xlsx"
    wb.save(path)
    return path
