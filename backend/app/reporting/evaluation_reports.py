"""Technical, commercial and consolidated workbooks. Read persisted results only; failed vendors are never shown as evaluated."""

from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation import engine
from app.models import CommercialSummary, CriterionFinding, Evaluation, EvaluationCriterion, Vendor
from app.reporting.certification_report import _Sheet, safe


def _criteria(db: Session, eid: str) -> dict[str, EvaluationCriterion]:
    return {c.criterion_code: c for c in db.scalars(select(EvaluationCriterion).where(EvaluationCriterion.evaluation_id == eid))}


def _req_text(c: EvaluationCriterion) -> str:
    val = c.required_text if c.comparator == "CONTAINS" else f"{c.required_value:g}" if c.required_value is not None else ""
    return f"{c.comparator} {val} {c.unit or ''}".strip()


def _criterion_sheet(wb: Workbook, db: Session, eid: str, kind: str, first: bool) -> None:
    crit = _criteria(db, eid)
    vendors = {v.id: v for v in db.scalars(select(Vendor).where(Vendor.evaluation_id == eid))}
    s = _Sheet(wb, f"{kind.title()} Criteria", ["Vendor", "Criterion", "Name", "Mandatory", "Weight", "Tender Requirement",
                                                "Tender Page", "Vendor Value", "Status", "Reasons", "Vendor Evidence",
                                                "Source Document", "Page", "Resolved By"],
               [24, 10, 28, 10, 8, 22, 9, 14, 20, 50, 55, 28, 7, 14], first=first)
    rows = db.scalars(select(CriterionFinding).where(CriterionFinding.evaluation_id == eid, CriterionFinding.kind == kind)
                      .order_by(CriterionFinding.criterion_code))
    for f in sorted(rows, key=lambda x: (vendors[x.vendor_id].name, x.criterion_code)):
        c, ev = crit.get(f.criterion_code), f.evidence or {}
        s.add([vendors[f.vendor_id].name, f.criterion_code, c.name if c else "", "Yes" if f.mandatory else "No", f.weight,
               _req_text(c) if c else "", c.source_page if c else None, ev.get("vendor_value"), f.status,
               "; ".join(f.reasons or []), ev.get("supporting_text"), ev.get("document_name"), ev.get("page_number"),
               f.resolved_by])
    s.finish(["Status"])


def build_technical(db: Session, eid: str) -> Workbook:
    wb = Workbook()
    ev = db.get(Evaluation, eid)
    _criterion_sheet(wb, db, eid, "TECHNICAL", first=True)
    s = _Sheet(wb, "Technical Summary", ["Vendor", "Certification", "Technical Status", "Score %", "Reason"], [26, 24, 20, 10, 70])
    for r in engine.build_results(db, eid):
        s.add([r.vendor_id and r.name, r.eligibility or "NOT SCREENED", r.technical["status"], r.technical.get("score"),
               r.technical.get("reason")])
    s.finish(["Technical Status", "Certification"])
    wb.move_sheet("Technical Summary", offset=-1)
    wb.properties.title = f"Technical evaluation - {ev.name}"
    return wb


def build_commercial(db: Session, eid: str) -> Workbook:
    wb = Workbook()
    s = _Sheet(wb, "Commercial Summary", ["Vendor", "Certification", "Commercial Status", "Currency", "Total Price", "Unit Price",
                                          "Quantity", "Taxes", "Taxes %", "Additional Charges", "Delivery (days)",
                                          "Payment (days)", "Validity (days)", "Review Notes"],
               [24, 22, 20, 9, 16, 14, 9, 14, 8, 14, 12, 12, 12, 60], first=True)
    for r in engine.build_results(db, eid):
        summ = db.get(CommercialSummary, r.vendor_id) if r.eligibility == "PASS" else None
        d = summ.data if summ else {}
        s.add([r.name, r.eligibility or "NOT SCREENED", r.commercial["status"], d.get("currency"), d.get("total_price"),
               d.get("unit_price"), d.get("quantity"), d.get("taxes_amount"), d.get("taxes_percent"),
               d.get("additional_charges"), d.get("delivery_days"), d.get("payment_days"), d.get("validity_days"),
               "; ".join(summ.review_reasons or []) if summ else r.commercial.get("reason")])
    s.finish(["Commercial Status", "Certification"])
    _criterion_sheet(wb, db, eid, "COMMERCIAL", first=False)
    return wb


def build_consolidated(db: Session, eid: str) -> Workbook:
    wb = Workbook()
    ev = db.get(Evaluation, eid)
    s = _Sheet(wb, "Final Comparison", ["Rank", "Vendor", "Certification", "Technical", "Technical Score %", "Commercial",
                                        "Total Price", "Currency", "Price Score", "Combined Score", "Rejection / Pending Reason"],
               [7, 26, 24, 18, 12, 18, 16, 9, 10, 12, 80], first=True)
    rows = engine.build_results(db, eid)
    for r in sorted(rows, key=lambda x: (x.rank is None, x.rank or 0, x.name)):
        if r.eligibility == "FAIL":
            reason = f"Certification failed: {r.eligibility_reason}"
        elif r.eligibility == "PENDING_HUMAN_REVIEW":
            reason = f"Pending human review: {r.eligibility_reason}"
        elif r.eligibility is None:
            reason = "Not screened"
        else:
            reason = "; ".join(r.notes) or ""
        s.add([r.rank, r.name, r.eligibility or "NOT SCREENED", r.technical["status"], r.technical.get("score"),
               r.commercial["status"], r.commercial.get("total_price"), r.commercial.get("currency"), r.price_score,
               r.combined_score, reason])
    s.finish(["Certification", "Technical", "Commercial"])
    cfg = engine.get_config(db, eid)
    n = wb.create_sheet("Notes")
    n.column_dimensions["A"].width = 100
    for line in (f"Evaluation: {ev.name}", f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
                 f"Order: {cfg.order}; weights technical {cfg.weight_technical} / commercial {cfg.weight_commercial}",
                 "Only vendors that PASSED certification screening are technically/commercially evaluated.",
                 "NOT_EVALUATED means the vendor never entered that stage; it is not a score of zero.",
                 "Ranking: qualified vendors only. Price score = lowest total price / vendor total price x 100.",
                 "Scores are computed deterministically from quoted evidence; the LLM never assigns scores."):
        n.append([safe(line)])
    return wb


def save(wb: Workbook, reports_dir: Path, eid: str, name: str) -> Path:
    out = reports_dir / eid
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.xlsx"
    wb.save(path)
    return path
