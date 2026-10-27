"""How a CV's content is worded and ordered (design D5): section order, headings, dates, terms and nesting.

This and styles.py are the only places to change for a different CV style; selection (tailor.py) and storage
(userdata.py) never word or order anything themselves.
"""

from __future__ import annotations

from collections import defaultdict

from ..enrich.terms import TERM_MONTHS
from .model import Bullet, Cv, Entry, Header, Paragraph, Section, is_course_group

SECTION_ORDER = (
    "goal", "summary", "highlights",
    "role", "course", "degree", "publication", "project", "award", "event", "task", "other",
)
HEADINGS = {
    "goal": "Statement of Goals",
    "summary": "Summary",
    "highlights": "Skills & Experience",
    "role": "Work Experience",
    "course": "Courses Taught",
    "degree": "Education",
    "publication": "Publications",
    "project": "Projects",
    "award": "Awards",
    "event": "Events",
    "task": "Tasks",
    "other": "Other",
}
# A kind's heading when some of its public records were left out of the CV.
SELECTED_HEADINGS = {"publication": "Selected Publications"}
HEADER_KINDS = ("name", "headline", "contact")  # details printed in the header; goal and summary are sections
PRINTED_SOURCE_KINDS = ("repo", "site", "doi")  # uploaded documents and other sources never print

SUBTITLE_SEPARATOR = " — "  # between an entry's title and its organisation and location
CONTACT_SEPARATOR = " · "
SOURCE_SEPARATOR = " · "
RANGE_SEPARATOR = " – "
PRESENT = "present"
CONTEXT_NOTE = "Part of: {}"

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def date_text(value: str) -> str:
    """'2022' -> '2022'; '2022-09' -> 'Sep 2022'."""
    year, _, month = value.partition("-")
    return f"{MONTHS[int(month) - 1][:3]} {year}" if month else year


def date_range(start: str | None, end: str | None, ongoing: bool = False) -> str | None:
    """A record's dates: 'start – end', 'start – present' when ongoing, the one date there is, or None."""
    if ongoing:
        return f"{date_text(start)}{RANGE_SEPARATOR}{PRESENT}" if start else PRESENT
    if start and end:
        return date_text(start) if start == end else f"{date_text(start)}{RANGE_SEPARATOR}{date_text(end)}"
    if start or end:
        return date_text(start or end)
    return None


def produced_month(day: str) -> str:
    """'2026-10-16' -> 'October 2026'."""
    year, month, _ = day.split("-", 2)
    return f"{MONTHS[int(month) - 1]} {year}"


def term_name(start: str | None, end: str | None) -> str | None:
    """'Winter 2024' when start and end are year-months within one term window of one year (enrich/terms.py),
    else None."""
    if not (start and end and "-" in start and "-" in end) or start[:4] != end[:4]:
        return None
    for season, (first, last) in TERM_MONTHS.items():
        if first <= start[5:7] and end[5:7] <= last:
            return f"{season.capitalize()} {start[:4]}"
    return None


def _term_key(term: dict) -> str:
    return term["start_date"] or term["end_date"] or ""


def terms_line(terms: list[dict]) -> str:
    """Every term, oldest first: named when it fits a term window, else as dates."""
    return ", ".join(
        term_name(t["start_date"], t["end_date"]) or date_range(t["start_date"], t["end_date"], t["ongoing"]) or "?"
        for t in sorted(terms, key=_term_key)
    )


def course_years(terms: list[dict]) -> str | None:
    """From the first term's start year to the last term's end year ('2024 – 2026', or one year)."""
    starts = [(t["start_date"] or t["end_date"])[:4] for t in terms if t["start_date"] or t["end_date"]]
    if not starts:
        return None
    if any(t["ongoing"] for t in terms):
        return f"{min(starts)}{RANGE_SEPARATOR}{PRESENT}"
    ends = [(t["end_date"] or t["start_date"])[:4] for t in terms if t["start_date"] or t["end_date"]]
    first, last = min(starts), max(ends)
    return first if first == last else f"{first}{RANGE_SEPARATOR}{last}"


def entry(payload: dict) -> Entry:
    """A record's or a course group's entry, with the records printed under it."""
    title = payload["title"] or payload["organisation"] or f"({payload['kind']})"
    rest = [payload["organisation"]] if payload["title"] and payload["organisation"] else []
    rest += [payload["location"]] if payload["location"] else []
    context = payload.get("context")
    if is_course_group(payload):
        dates = course_years(payload["terms"])
        lines = (terms_line(payload["terms"]), *payload["lines"])
    else:
        dates = date_range(payload["start_date"], payload["end_date"], payload["ongoing"])
        lines = tuple(payload["lines"])
    return Entry(
        title=title,
        subtitle=", ".join(rest) or None,
        dates=dates,
        lines=lines,
        sources=tuple(payload["sources"]),
        context_note=CONTEXT_NOTE.format(context["title"] or context["organisation"]) if context else None,
        children=tuple(entry(child) for child in payload["children"]),
    )


def _detail_text(payload: dict) -> str:
    return f"{payload['label']}: {payload['text']}" if payload.get("label") else payload["text"]


def build(content: dict) -> Cv:
    """The laid-out CV: the header (name, headline, the produced month, labelled contacts), then the sections in
    SECTION_ORDER, empty ones left out, items in their given order."""
    by_section: dict[str, list[dict]] = defaultdict(list)
    for item in content["items"]:
        by_section[item["section"]].append(item["payload"])
    details = by_section.get("header", [])

    def joined(kind: str) -> str | None:
        return CONTACT_SEPARATOR.join(d["text"] for d in details if d["kind"] == kind) or None

    header = Header(
        name=joined("name"),
        headline=joined("headline"),
        produced=produced_month(content["produced"]),
        contacts=tuple(_detail_text(d) for d in details if d["kind"] == "contact"),
    )
    left_out = set(content.get("left_out", ()))
    sections = []
    for key in SECTION_ORDER:
        payloads = by_section.get(key)
        if not payloads:
            continue
        if key in ("goal", "summary"):
            blocks = tuple(Paragraph(p["text"]) for p in payloads)
        elif key == "highlights":
            blocks = tuple(Bullet(p["text"]) for p in payloads)
        else:
            blocks = tuple(entry(p) for p in payloads)
        heading = SELECTED_HEADINGS.get(key, HEADINGS[key]) if key in left_out else HEADINGS[key]
        sections.append(Section(key, heading, blocks))
    return Cv(header, tuple(sections))


def entry_heading(e: Entry) -> str:
    """An entry's first line as plain text: title, subtitle, then a tab and the dates."""
    text = e.title + (SUBTITLE_SEPARATOR + e.subtitle if e.subtitle else "")
    return text + ("\t" + e.dates if e.dates else "")


def _entry_text(e: Entry) -> list[str]:
    out = [entry_heading(e), *e.lines]
    if e.sources:
        out.append(SOURCE_SEPARATOR.join(e.sources))
    if e.context_note:
        out.append(e.context_note)
    for child in e.children:
        out += _entry_text(child)
    return out


def text(cv: Cv) -> list[str]:
    """The CV's paragraphs as plain text, in print order (what an export reads back as)."""
    h = cv.header
    out = [line for line in (h.name, h.headline, h.produced) if line]
    if h.contacts:
        out.append(CONTACT_SEPARATOR.join(h.contacts))
    for section in cv.sections:
        out.append(section.heading)
        for block in section.blocks:
            out += _entry_text(block) if isinstance(block, Entry) else [block.text]
    return out
