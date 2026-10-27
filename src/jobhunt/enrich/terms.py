"""Terms taught: "Taught Fall 2026, Winter 2026" -> one dated term each, by rule (no model, no database).

Course work is stored as one record per term (design D4). A term's months are Winter January to April, Summer May
to August and Fall September to December of its year. Only the strict form is matched: "Taught" and one or more
"<Term> <Year>", separated by commas or "and"; anything else stays a description line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TERM_MONTHS = {"winter": ("01", "04"), "summer": ("05", "08"), "fall": ("09", "12")}

_TERM = r"(Winter|Summer|Fall)\s+(\d{4})"
_SEPARATOR = r"\s*(?:,\s*and\b|,|\band\b)\s*"
_LINE = re.compile(rf"Taught\s+{_TERM}(?:{_SEPARATOR}{_TERM})*\s*\.?", re.IGNORECASE)
_EACH = re.compile(_TERM, re.IGNORECASE)


@dataclass(frozen=True)
class Term:
    season: str  # 'Winter', 'Summer' or 'Fall'
    year: str
    start: str  # partial ISO dates: '2026-09'
    end: str


def terms(line: str) -> list[Term] | None:
    """The terms a "Taught ..." line names, in the order written; None when the line isn't one."""
    text = " ".join(line.split())
    if not _LINE.fullmatch(text):
        return None
    out = []
    for season, year in _EACH.findall(text):
        first, last = TERM_MONTHS[season.casefold()]
        out.append(Term(season.capitalize(), year, f"{year}-{first}", f"{year}-{last}"))
    return out
