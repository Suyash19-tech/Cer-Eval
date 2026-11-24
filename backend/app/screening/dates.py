"""Deterministic date parsing. Ambiguity is reported, never guessed."""

import calendar
import re
from datetime import date

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MON = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("dmy_name", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[ \-./]*{_MON}\.?[ \-./,]*(\d{{4}})\b", re.I)),
    ("mdy_name", re.compile(rf"\b{_MON}\.? (\d{{1,2}})(?:st|nd|rd|th)?,? (\d{{4}})\b", re.I)),
    ("numeric", re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")),
]


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> tuple[list[date], bool]:
    """Return (unambiguous dates found, ambiguous_or_invalid_seen). Overlapping matches are consumed once."""
    found: list[date] = []
    bad = False
    work = text
    for kind, pat in _PATTERNS:
        def repl(m: re.Match) -> str:
            nonlocal bad
            g = m.groups()
            d: date | None
            if kind == "iso":
                d = _mk(int(g[0]), int(g[1]), int(g[2]))
            elif kind == "dmy_name":
                d = _mk(int(g[2]), _MONTHS[g[1].lower()[:3]], int(g[0]))
            elif kind == "mdy_name":
                d = _mk(int(g[2]), _MONTHS[g[0].lower()[:3]], int(g[1]))
            else:
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                if a > 12 or a == b:
                    d = _mk(y, b, a)
                elif b > 12:
                    d = _mk(y, a, b)
                else:
                    d = None  # 03/04/2027: day-first or month-first? do not guess
            if d is None:
                bad = True
            else:
                found.append(d)
            return " " * len(m.group(0))

        work = pat.sub(repl, work)
    return found, bad


def add_months(d: date, months: int) -> date:
    idx = d.month - 1 + months
    y, m = d.year + idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
