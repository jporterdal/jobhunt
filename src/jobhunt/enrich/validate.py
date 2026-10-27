"""Checks every model item against the description text, then merges duplicate skills. Pure Python.

Normalising case-folds, collapses whitespace and maps typographic dashes and quotes to ASCII, keeping a map
from each normalised character back to its raw position so verified items can store raw offsets.
"""

from __future__ import annotations

import re

from ..userdata import name_key
from .pipeline import IMPORTANCES, Checked, SalaryItem, SkillItem

NAME = "v"
VERSION = 3  # bump when a check gets stricter or looser: it changes results

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "‘’‚‛′"), "'") | dict.fromkeys(
    map(ord, "“”„‟″"), '"'
)
_ASCII = _DASHES | _QUOTES
AMOUNT_TOLERANCE = 0.005


def normalise(text: str) -> tuple[str, list[int]]:
    """(normalised text, raw index of each normalised character). Leading and trailing space is dropped."""
    out: list[str] = []
    positions: list[int] = []
    pending_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            pending_space = bool(out)
            continue
        if pending_space:
            out.append(" ")
            positions.append(i - 1)
            pending_space = False
        for folded in ch.translate(_ASCII).casefold():
            out.append(folded)
            positions.append(i)
    return "".join(out), positions


def occurrences(haystack: str, needle: str) -> list[int]:
    """Start of every whole-word occurrence of the needle in the (normalised) haystack, or of every occurrence
    when none is whole-word. Only the needle's own edges are checked: "c#" ends in no letter or digit, so
    nothing after it matters."""
    found = []
    at = haystack.find(needle)
    while at >= 0:
        found.append(at)
        at = haystack.find(needle, at + 1)

    def whole(at: int) -> bool:
        end = at + len(needle)
        before = not needle[0].isalnum() or at == 0 or not haystack[at - 1].isalnum()
        after = not needle[-1].isalnum() or end == len(haystack) or not haystack[end].isalnum()
        return before and after

    return [a for a in found if whole(a)] or found


def locate(text: str, quote: str, within: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """Raw (start, end) of the quote in the text, or None. Looked for inside `within` first, then in the whole
    text; in each, the first whole-word occurrence wins, else the first occurrence of any kind."""
    needle, _ = normalise(quote)
    if not needle:
        return None
    for start, end in ([within] if within else []) + [(0, len(text))]:
        haystack, positions = normalise(text[start:end])
        found = occurrences(haystack, needle)
        if found:
            return start + positions[found[0]], start + positions[found[0] + len(needle) - 1] + 1
    return None


_NUMBER = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?[kK](?![a-zA-Z]))?")


def amounts_in(quote: str) -> list[float]:
    """Every amount written in the quote: 175,000 175000 175k 175K 2,950.40.

    In "175-200k" the k applies to both ends, so when any amount has a k, bare amounts under 1000
    also count in thousands.
    """
    found: list[float] = []
    bare_small: list[float] = []
    has_k = False
    for whole, fraction, k in _NUMBER.findall(quote):
        value = float(whole.replace(",", "") + (fraction or ""))
        if k:
            has_k = True
            value *= 1000
        elif value < 1000:
            bare_small.append(value * 1000)
        found.append(value)
    return found + (bare_small if has_k else [])


def amount_in(amount: float, quote_amounts: list[float]) -> bool:
    return any(abs(amount - q) <= AMOUNT_TOLERANCE * max(abs(amount), abs(q)) for q in quote_amounts)


def check_skills(text: str, items: list[SkillItem]) -> list[Checked]:
    out = []
    for item in items:
        span = locate(text, item.quote, item.source)
        out.append(Checked(item, True, *span) if span else Checked(item, False))
    return out


def merge_skills(checked: list[Checked]) -> list[Checked]:
    """Higher importance wins: among verified items with the same skill key, keep the first at the highest
    importance. Unverified items pass through, so an invented quote can't knock out a verified twin."""
    best: dict[str, int] = {}
    for i, c in enumerate(checked):
        if not c.verified:
            continue
        key = name_key(c.item.name)
        kept = best.get(key)
        if kept is None or IMPORTANCES.index(c.item.importance) < IMPORTANCES.index(checked[kept].item.importance):
            best[key] = i
    keep = set(best.values())
    return [c for i, c in enumerate(checked) if not c.verified or i in keep]


def check_salaries(text: str, items: list[SalaryItem]) -> list[Checked]:
    """A range is verified when its quote is in the text and it has at least one amount, each in the quote."""
    out = []
    for item in items:
        span = locate(text, item.quote)
        amounts = [a for a in (item.min, item.max) if a is not None]
        written = amounts_in(item.quote)
        ok = span is not None and bool(amounts) and all(amount_in(a, written) for a in amounts)
        out.append(Checked(item, True, *span) if ok else Checked(item, False))
    return out
