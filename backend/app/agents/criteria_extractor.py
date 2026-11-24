"""Tender technical/commercial criteria: LLM proposes grounded items; Python verifies; a human confirms."""

import re

from app.agents.tender_extractor import StructuredLLM, find_quote_page, implied_mandatory, make_windows, normalize
from app.evaluation.compare import Comparator
from app.evaluation.units import normalize_unit, numbers_in, parse_quantities
from app.schemas.criteria import COMMERCIAL_PARAMS, LLMCriterion, LLMCriterionList
from app.schemas.documents import PageText

CRITERIA_WINDOW_CHARS = 1  # one page per prompt (a window never merges pages)

INSTRUCTION = f"""Extract the TECHNICAL specifications and COMMERCIAL conditions that a vendor's offer must satisfy, from the tender text.
Do NOT extract certification or standard-compliance requirements (AS9100, ISO ..., NADCAP) or certificate validity.

Rules:
- supporting_text: copy the exact sentence from the tender. Never paraphrase.
- kind: TECHNICAL for product/service performance, dimensions, materials, capacity; COMMERCIAL for price, delivery,
  payment, quotation validity, quantity.
- comparator: GTE for "at least/minimum/not less than", LTE for "at most/not exceed/within/not more than",
  EQ for an exact number, CONTAINS for a required wording or material (then put the wording in required_text,
  and leave required_value null).
- required_value and unit: only the number and unit written in the sentence. Use null if there is none.
- parameter (COMMERCIAL only): one of {list(COMMERCIAL_PARAMS)} when it fits, e.g. delivery period -> delivery_days
  (unit days), payment terms -> payment_days, quotation validity -> validity_days. Otherwise null.
- mandatory=true for shall/must/required; false for desirable/preferred/may.
- Never invent a requirement. If the tender has none, return an empty list.

Example sentence: "3.1 The pump shall deliver a maximum operating pressure of at least 250 bar."
Example item: {{"kind":"TECHNICAL","name":"Maximum operating pressure","parameter":null,"comparator":"GTE","required_value":250,
"required_text":null,"unit":"bar","mandatory":true,"supporting_text":"3.1 The pump shall deliver a maximum operating pressure of at least 250 bar."}}
Example sentence: "3.3 The housing material shall be stainless steel."
Example item: {{"kind":"TECHNICAL","name":"Housing material","parameter":null,"comparator":"CONTAINS","required_value":null,
"required_text":"stainless steel","unit":null,"mandatory":true,"supporting_text":"3.3 The housing material shall be stainless steel."}}
Example sentence: "Delivery shall be completed within 90 days of the purchase order."
Example item: {{"kind":"COMMERCIAL","name":"Delivery period","parameter":"delivery_days","comparator":"LTE","required_value":90,
"required_text":null,"unit":"days","mandatory":true,"supporting_text":"Delivery shall be completed within 90 days of the purchase order."}}"""


_CLAUSE = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")
_GTE = re.compile(r"\b(at least|not less than|no less than|minimum of|a minimum|min\.?|greater than or equal)\b", re.I)
_LTE = re.compile(r"\b(at most|not exceed|no more than|not more than|up to|within|maximum of|a maximum of|not later than)\b", re.I)
_CERTISH = re.compile(r"\b(certificat\w*|accredit\w*|AS ?9\d{3}|ISO(?:/IEC)? ?\d{4,5}|NADCAP|EN ?\d{4,5})\b", re.I)
_COMMERCIAL_PARAM = ((re.compile(r"\bdeliver", re.I), "delivery_days"), (re.compile(r"\bpayment", re.I), "payment_days"),
                     (re.compile(r"\b(valid|validity)\b", re.I), "validity_days"))


def strip_clause(text: str) -> str:
    """Remove a leading clause number ('3.1 ') so it is never mistaken for a required value."""
    return _CLAUSE.sub("", text, count=1)


def is_certification(text: str) -> bool:
    return bool(_CERTISH.search(text))


def infer_comparator(text: str) -> Comparator | None:
    g, l = bool(_GTE.search(text)), bool(_LTE.search(text))
    if g and not l:
        return Comparator.GTE
    if l and not g:
        return Comparator.LTE
    return Comparator.GTE if g and re.search(r"at least|not less than", text, re.I) else None


def verify(c: LLMCriterion, pages: list[PageText]) -> dict:
    reasons: list[str] = []
    page = find_quote_page(c.supporting_text, pages)
    if page is None:
        reasons.append("Supporting text not found verbatim in tender; possible hallucination")
    value, unit, text, param = c.required_value, c.unit, c.required_text, c.parameter
    body = strip_clause(c.supporting_text)
    nums = numbers_in(body)
    comparator = c.comparator
    if comparator != Comparator.CONTAINS and not nums and c.required_text and normalize(c.required_text) in normalize(body):
        comparator = Comparator.CONTAINS  # wording requirement the model mislabelled as numeric
        reasons.append("Comparator changed to CONTAINS (no number in the sentence)")
    inferred = infer_comparator(body) if comparator != Comparator.CONTAINS else None
    if inferred and inferred != comparator:
        reasons.append(f"Comparator {comparator.value} contradicts the tender wording; using {inferred.value}")
        comparator = inferred
    if comparator == Comparator.CONTAINS:
        value = None
        if not text or normalize(text) not in normalize(c.supporting_text):
            reasons.append("Required wording not present in supporting text")
            text = None
    else:
        text = None
        if value is None or not any(abs(value - n) < 1e-9 for n in nums):
            if len(nums) == 1:
                value = nums[0]  # deterministic gap-filler: the one number in the sentence
                if c.required_value is not None:
                    reasons.append("Required value was not in the quote as given; replaced with the number in the quote")
            else:
                reasons.append("Required value missing or not found in supporting text")
                value = None
    if unit is None and value is not None:
        q = [x for x in parse_quantities(body) if x.unit and abs(x.value - value) < 1e-9]
        if len(q) == 1:
            unit = q[0].unit
    if unit and not re.search(r"(?<![a-z])" + re.escape(normalize_unit(unit) or unit) + r"(?![a-z])", normalize(c.supporting_text).replace("°", "")):
        reasons.append(f"Unit '{unit}' not present in supporting text; removed")
        unit = None
    if c.kind == "COMMERCIAL":
        if param not in COMMERCIAL_PARAMS:
            param = None
        if param is None and unit in ("day", "days", "week", "weeks", "month", "months"):
            hits = [p for rx, p in _COMMERCIAL_PARAM if rx.search(body)]
            param = hits[0] if len(hits) == 1 else None
    else:
        param = None
    implied = implied_mandatory(c.supporting_text)
    if implied is not None and implied != c.mandatory:
        reasons.append(f"Mandatory flag ({c.mandatory}) contradicts the tender wording")
    return {"kind": c.kind, "name": c.name.strip()[:255], "parameter": param, "comparator": comparator.value,
            "required_value": value, "required_text": text, "unit": unit, "mandatory": c.mandatory,
            "source_page": page, "supporting_text": c.supporting_text, "needs_human_review": bool(reasons),
            "review_reasons": reasons}


def extract_criteria(llm: StructuredLLM, pages: list[PageText]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    # one page per prompt: with several pages in one prompt the 8B model stops listing after the first few items
    for window in make_windows(pages, limit=CRITERIA_WINDOW_CHARS):
        for raw in llm.extract(LLMCriterionList, INSTRUCTION, window, max_tokens=2048).criteria:
            key = normalize(raw.supporting_text)
            if key in seen:
                continue
            seen.add(key)
            if is_certification(raw.supporting_text):
                continue  # certification requirements belong to the certification stage, never to criteria
            out.append(verify(raw, pages))
    counters = {"TECHNICAL": 0, "COMMERCIAL": 0}
    for item in out:
        counters[item["kind"]] += 1
        item["criterion_code"] = f"{'TECH' if item['kind'] == 'TECHNICAL' else 'COM'}-{counters[item['kind']]:03d}"
    return out
