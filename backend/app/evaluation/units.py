"""Deterministic quantity parsing and unit conversion. Never guesses: unknown units return None."""

import re
from dataclasses import dataclass

# unit -> (family, factor to the family's base unit)
_UNITS: dict[str, tuple[str, float]] = {
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0), "km": ("length", 1000.0), "in": ("length", 0.0254),
    "g": ("mass", 0.001), "kg": ("mass", 1.0), "t": ("mass", 1000.0), "lb": ("mass", 0.45359237),
    "day": ("time", 1.0), "days": ("time", 1.0), "week": ("time", 7.0), "weeks": ("time", 7.0),
    "month": ("time", 30.0), "months": ("time", 30.0), "year": ("time", 365.0), "years": ("time", 365.0),
    "hour": ("hours", 1.0), "hours": ("hours", 1.0), "h": ("hours", 1.0),
    "pa": ("pressure", 1.0), "kpa": ("pressure", 1e3), "mpa": ("pressure", 1e6), "bar": ("pressure", 1e5), "psi": ("pressure", 6894.757),
    "w": ("power", 1.0), "kw": ("power", 1e3), "mw": ("power", 1e6),
    "v": ("voltage", 1.0), "kv": ("voltage", 1e3),
    "%": ("percent", 1.0), "percent": ("percent", 1.0),
    "c": ("temp_c", 1.0), "°c": ("temp_c", 1.0), "degc": ("temp_c", 1.0),
    "hz": ("freq", 1.0), "khz": ("freq", 1e3), "mhz": ("freq", 1e6),
}
_NUM = r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_QTY = re.compile(_NUM + r"\s*(°\s?[CcFf]|%|[A-Za-z]+)?")


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str | None  # normalised lower-case token as written, or None


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    u = unit.strip().lower().replace("°", "").replace(" ", "")
    if u in ("degc", "c") and "°" in unit:
        return "°c"
    return {"percent": "%", "pct": "%"}.get(u, u)


def parse_quantities(text: str) -> list[Quantity]:
    out = []
    for m in _QTY.finditer(text):
        num = float(m.group(1).replace(",", ""))
        unit = normalize_unit(m.group(2))
        out.append(Quantity(num, unit if unit in _UNITS else None))
    return out


def numbers_in(text: str) -> list[float]:
    return [float(m.group(1).replace(",", "")) for m in re.finditer(_NUM, text)]


def to_base(q: Quantity) -> tuple[str, float] | None:
    if q.unit is None or q.unit not in _UNITS:
        return None
    fam, factor = _UNITS[q.unit]
    return fam, q.value * factor


def convert(value: float, from_unit: str | None, to_unit: str | None) -> float | None:
    """Convert between units of one family; None if impossible. Unitless <-> unitless passes through."""
    f, t = normalize_unit(from_unit), normalize_unit(to_unit)
    if f == t:
        return value
    if f not in _UNITS or t not in _UNITS or _UNITS[f][0] != _UNITS[t][0]:
        return None
    return value * _UNITS[f][1] / _UNITS[t][1]
