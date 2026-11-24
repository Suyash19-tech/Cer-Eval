"""Deterministic parsing of amounts, quantities and durations from quoted vendor text."""

import re
from dataclasses import dataclass

from app.evaluation.units import Quantity, convert, parse_quantities

_CUR = {"inr": "INR", "rs": "INR", "rs.": "INR", "₹": "INR", "usd": "USD", "$": "USD", "eur": "EUR", "€": "EUR",
        "gbp": "GBP", "£": "GBP"}
_MONEY = re.compile(r"(?:(INR|USD|EUR|GBP|Rs\.?|₹|\$|€|£)\s*)?(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(INR|USD|EUR|GBP))?",
                    re.I)


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str | None


def parse_money(text: str) -> list[Money]:
    """Amounts that carry a currency marker. Plain numbers are not money (avoids reading '18 %' or '90 days')."""
    out = []
    for m in _MONEY.finditer(text):
        cur = (m.group(1) or m.group(3) or "").lower()
        if cur:
            out.append(Money(float(m.group(2).replace(",", "")), _CUR[cur]))
    return out


def parse_percent(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)]


def parse_days(text: str) -> tuple[float | None, str | None]:
    """(days, problem). Exactly one duration expected; weeks/months converted (30-day month)."""
    durations = [q for q in parse_quantities(text) if q.unit and convert(1.0, q.unit, "days") is not None]
    if not durations:
        return None, "No duration found"
    values = {convert(q.value, q.unit, "days") for q in durations}
    if len(values) > 1:
        return None, "Several different durations in the quoted text"
    return values.pop(), None


def parse_quantity_count(text: str) -> tuple[float | None, str | None]:
    nums: list[Quantity] = [q for q in parse_quantities(text)]
    if len({q.value for q in nums}) != 1:
        return None, "Quantity missing or ambiguous"
    return nums[0].value, None
