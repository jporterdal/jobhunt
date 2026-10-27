"""The document pipeline: a document's text -> suggestions for the profile (records with their lines and sources,
claims with their grounds, highlights with the claims they cover, and context links). No database, no HTTP.

Steps keep the span contract: every line is a pair of offsets into the document's text_content, the model
answers with line numbers and quotes, and every quote is checked against the text (validate.locate), so a
suggestion only ever holds text the document holds.

1. caps@1 (rules): headings split the text into sections; lines before the first one are the contact block.
   Contact and summary sections are never sent to the model and suggest nothing (details are the user's).
2. llm@1: the model labels each line of a section entry, bullet, detail or text, with quotes for an entry's
   fields and dates. A date after a tab at the end of a line is that line's date.
3. rules@1 (records): entries become records, the lines after them their description lines (a lone web address a
   source), lines before any entry and every claims line highlights; "Taught <Term> <Year>, ..." splits a record
   into one course record per term (enrich/terms.py), and an undated record takes its dates from its lines.
4. cv-claims@1: the model lists the skills each line shows the person has, with a suggested level; each becomes a
   claim grounded by the record holding its line, or covered by the highlight that is its line.
5. part-of@1: the model says which of the run's records is part of which, under the user's guideline.
"""

from __future__ import annotations

import re
import string
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..userdata import MODEL_LEVELS, level_rank, name_key, source_kind
from . import validate
from .pipeline import LLM, SKILL_KINDS, Cancelled, DocumentResult, StepFailed, _Recorder, conform
from .segment import batches, lines
from .terms import terms

# --- caps@1: sections from headings (rules) ---

HEADING_MAX = 60
# Checked in this order; the first that matches the heading gives the kind.
SECTION_KEYWORDS = (
    (re.compile(r"\b(summary|goals?|objectives?|profile)"), "summary"),
    (re.compile(r"\bskills?\b"), "claims"),
    (re.compile(r"\b(experience|employment|work|teaching)"), "experience"),
    (re.compile(r"\beducation"), "education"),
    (re.compile(r"\bpublication"), "publication"),
    (re.compile(r"\bproject"), "project"),
)
LABELLED_KINDS = ("experience", "education", "publication", "project", "other")  # claims lines are all highlights
SKILL_SECTION_KINDS = ("claims", "experience", "education", "publication", "project")


@dataclass
class Section:
    name: str
    kind: str
    lines: list[tuple[int, int]]  # spans of its content lines, the heading left out
    heading: tuple[int, int] | None = None


def heading_text(line: str) -> str | None:
    """The heading in a line, or None: the text before its first tab, at most 60 characters, with at least two
    letters, every one a capital."""
    head = line.split("\t", 1)[0].strip()
    letters = [c for c in head if c.isalpha()]
    if len(head) <= HEADING_MAX and len(letters) >= 2 and all(c.isupper() for c in letters):
        return head
    return None


def section_kind(heading: str) -> str:
    folded = heading.casefold()
    for pattern, kind in SECTION_KEYWORDS:
        if pattern.search(folded):
            return kind
    return "other"


class CapsSections:
    name = "caps"
    version = 1

    def sections(self, text: str) -> list[Section]:
        out = [Section("Contact", "contact", [])]
        for start, end in lines(text):
            head = heading_text(text[start:end])
            if head is not None:
                out.append(Section(string.capwords(head), section_kind(head), [], (start, end)))
            else:
                out[-1].lines.append((start, end))
        return [s for s in out if s.lines or s.heading]


# --- Dates ---

MONTHS = {
    m: i for i, names in enumerate(
        (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
         ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
         ("dec", "december")),
        start=1,
    ) for m in names
}
PRESENT = ("present", "current", "now", "ongoing", "today")
PRESENT_MARK = "present"
_RANGE = re.compile(r"^(.+?)\s*(?:[–—]|-{1,2}|\bto\b|\buntil\b)\s*(.+)$", re.IGNORECASE)


def parse_date(quote: str) -> str | None:
    """'2019', '2019-09' or 'present' from a date as written ('2019', 'Sep 2019', '09/2019', 'Present'), else None."""
    q = quote.strip().strip(".,;()").casefold()
    if q in PRESENT:
        return PRESENT_MARK
    if re.fullmatch(r"(19|20)\d{2}", q):
        return q
    m = re.fullmatch(r"((?:19|20)\d{2})[-/.](\d{1,2})", q) or None
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})[-/.]((?:19|20)\d{2})", q)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"([a-z]+)\.?,?\s+((?:19|20)\d{2})", q)
    if m and m.group(1) in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1)]:02d}"
    return None


def parse_dates(quote: str) -> tuple[str | None, str | None] | None:
    """(start, end) from a single date (as the end) or a range; None when it doesn't read as dates."""
    single = parse_date(quote)
    if single is not None:
        return None, single
    m = _RANGE.match(quote.strip())
    if m:
        start, end = parse_date(m.group(1)), parse_date(m.group(2))
        if start and end and start != PRESENT_MARK:
            return start, end
    return None


def tail_dates(line: str) -> tuple[int, str | None, str | None] | None:
    """(offset of the tail in the line, start, end) when the text after the line's last tab reads as dates."""
    if "\t" not in line:
        return None
    at = line.rindex("\t")
    parsed = parse_dates(line[at + 1:])
    return (at, *parsed) if parsed else None


def _dated(values: dict, start: str | None, end: str | None, entry: bool) -> None:
    if end == PRESENT_MARK:
        end = None
        if entry:
            values["ongoing"] = True
    values["start_date"], values["end_date"] = start, end


# --- llm@1: line labels and fields ---

LINE_LABELS = ("entry", "bullet", "detail", "text")
_FIELD = {"type": ["string", "null"]}
LINES_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "label": {"type": "string", "enum": list(LINE_LABELS)},
                    "title": _FIELD,
                    "organisation": _FIELD,
                    "location": _FIELD,
                    "start": _FIELD,
                    "end": _FIELD,
                },
                "required": ["line", "label"],
            },
        }
    },
    "required": ["lines"],
}

LINES_SYSTEM = """You read the numbered lines of one section of a CV, headed "{heading}".
Label every line:
- "entry": starts a new role, degree, award, paper or project (for example "PhD Computer Science, Dalhousie
  University" or "Data Scientist, Acme Corp, Toronto")
- "bullet": a point listed under an entry or the section (an achievement, a duty, a claim)
- "detail": continues the entry above it (a thesis title, a course taught, a supervisor, a line of a citation)
- "text": a sentence of prose
For an "entry", also give quotes copied character for character from the line:
- "title": the role, degree or paper title
- "organisation": the employer, university, venue or publisher
- "location": the city or country, if the line names one
For any line, give its dates as quotes from the line: "start" and "end", or only "end" for a single date.
Use "end": "present" when the line says present, current or now.
A tab followed by a year at the end of a line is that line's date.
Use null for anything the line doesn't state.
Answer with JSON: {{"lines": [{{"line": <number>, "label": "...", "title": ..., "organisation": ..., "location": ...,
"start": ..., "end": ...}}]}}."""


class LineLabeller:
    name = "llm"
    version = 1

    def label(self, text: str, section: Section, llm: LLM) -> dict[int, dict]:
        """Line index -> the model's answer for it; lines it left out are absent."""
        numbered = [f"{n}: {text[s:e]}" for n, (s, e) in enumerate(section.lines, start=1)]
        system = LINES_SYSTEM.format(heading=section.name)
        out: dict[int, dict] = {}
        for group in batches(numbered, llm.num_ctx):
            response = conform(
                "lines", llm.chat_json(system, "\n".join(numbered[i] for i in group), LINES_SCHEMA), LINES_SCHEMA
            )
            asked = {i + 1 for i in group}
            for entry in response["lines"]:
                if entry["line"] in asked:
                    out[entry["line"] - 1] = entry
        return out


# --- rules@1 (records): records, lines, sources and highlights from the labelled lines ---

SEPARATORS = " \t|,;:·•–—-/()[]"
RECORD_KIND = {"experience": "role", "education": "degree", "publication": "publication", "project": "project"}
ADDRESS = re.compile(r"(?:https?://|www\.)\S+|(?:[\w-]+\.)+[a-z]{2,}/\S*", re.IGNORECASE)


def is_address(text: str) -> bool:
    """A line that is a single web address (it becomes a source, not a description line)."""
    return bool(ADDRESS.fullmatch(text.strip()))


@dataclass
class _Entry:
    """An entry as its lines are read, before it becomes one record (or one per term)."""

    fields: dict
    lines: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    line_dates: list[str] = field(default_factory=list)
    taught: list | None = None


@dataclass
class _Built:
    """The run's suggestions as they are assembled, with where each line's skills attach."""

    records: list[dict] = field(default_factory=list)
    highlights: list[dict] = field(default_factory=list)
    # line start -> ("record", [record positions]) or ("highlight", [position]); entries resolve to records last
    targets: dict[int, tuple[str, list[int]]] = field(default_factory=dict)
    unverified: dict[str, list] = field(
        default_factory=lambda: {"fields": [], "dates": [], "skills": [], "part_of": []}
    )


def _strip_bullet(text: str) -> str:
    return re.sub(r"^\s*(?:[-*•●▪◦‣]|\d+[.)])\s+", "", text)


def _in_line(text: str, quote: str | None, span: tuple[int, int]) -> tuple[int, int] | None:
    """The quote's location if it is inside the line."""
    if not quote:
        return None
    found = validate.locate(text, quote, span)
    return found if found and span[0] <= found[0] and found[1] <= span[1] else None


def _line_dates(
    text: str, answer: dict, span: tuple[int, int], built: _Built
) -> tuple[str | None, str | None, list[tuple[int, int]], int]:
    """(start, end, spans the dates use, where the line's text ends) for a line: the dates after its last tab,
    else the model's date quotes that are in the line and read as dates."""
    line = text[span[0]:span[1]]
    tail = tail_dates(line)
    if tail is not None:
        at, start, end = tail
        return start, end, [(span[0] + at, span[1])], span[0] + at
    dates, used = {}, []
    for which in ("start", "end"):
        quote = answer.get(which)
        if not quote:
            continue
        located = _in_line(text, quote, span)
        value = parse_date(text[located[0]:located[1]]) if located else None
        if value is None:
            built.unverified["dates"].append({"line": line, which: quote})
            continue
        dates[which] = value
        used.append(located)
    return dates.get("start"), dates.get("end"), used, span[1]


def _leftover(text: str, span: tuple[int, int], used: list[tuple[int, int]]) -> str | None:
    """Text of the line outside the used spans, with separators trimmed; None when nothing is left."""
    pieces, start = [], span[0]
    for a, b in sorted(used):
        if a > start:
            pieces.append((start, a))
        start = max(start, b)
    if start < span[1]:
        pieces.append((start, span[1]))
    kept = [(a, b) for a, b in pieces if sum(c.isalnum() for c in text[a:b]) >= 1]
    words = " ".join(" ".join(text[a:b].split()) for a, b in kept).strip(SEPARATORS + " ")
    if sum(c.isalpha() for c in words) < 3:
        return None
    return _strip_bullet(words)


def _entry_fields(text: str, section: Section, answer: dict, span: tuple[int, int], dates, built: _Built):
    """(record fields, spans the fields use) for an entry line."""
    start, end, date_spans, text_end = dates
    values = {"kind": RECORD_KIND.get(section.kind, "other"), "location": None, "ongoing": False}
    used = list(date_spans)
    line = text[span[0]:span[1]]
    for name in ("title", "organisation", "location"):
        quote = answer.get(name)
        located = validate.locate(text, quote, span) if quote else None
        if quote and located is None:
            built.unverified["fields"].append({"line": line, name: quote})
        values[name] = " ".join(text[located[0]:located[1]].split()) if located else None
        if located and span[0] <= located[0] and located[1] <= span[1]:
            used.append(located)
    if not values["title"] and not values["organisation"]:
        values["title"] = _strip_bullet(" ".join(text[span[0]:text_end].split()))
        used.append((span[0], text_end))
    _dated(values, start, end, entry=True)
    return values, used


def _record_versions(entry: _Entry) -> list[dict]:
    """The records an entry becomes: one per term taught, else one, dated from its lines when it has no dates."""
    if entry.taught:
        return [
            {**entry.fields, "kind": "course", "start_date": t.start, "end_date": t.end, "ongoing": False}
            for t in entry.taught
        ]
    values = dict(entry.fields)
    if not values["start_date"] and not values["end_date"] and not values["ongoing"] and entry.line_dates:
        dates = sorted(set(entry.line_dates))
        values["start_date"], values["end_date"] = (dates[0] if len(dates) > 1 else None), dates[-1]
    return [values]


class RecordRules:
    """Records, lines, sources and highlights from a section's labelled lines; no model."""

    name = "rules"
    version = 1

    def build(self, text: str, section: Section, answers: dict[int, dict], built: _Built) -> None:
        if section.kind == "claims":
            for span in section.lines:
                self._highlight(text, span, span[1], built)
            return
        entries: list[_Entry] = []
        attached: list[tuple[int, int]] = []  # (line start, entry index)
        for n, span in enumerate(section.lines):
            answer = answers.get(n, {"label": "bullet"})
            dates = _line_dates(text, answer, span, built)
            start, end, _, text_end = dates
            if answer["label"] == "entry":
                values, used = _entry_fields(text, section, answer, span, dates, built)
                entries.append(_Entry(values))
                rest = _leftover(text, span, used)
                if rest is not None:
                    entries[-1].lines.append(rest)
                attached.append((span[0], len(entries) - 1))
                continue
            if not entries:  # before any entry: a section's introduction
                self._highlight(text, span, text_end, built)
                continue
            entry = entries[-1]
            entry.line_dates += [d for d in (start, end) if d and d != PRESENT_MARK]
            line = _strip_bullet(" ".join(text[span[0]:text_end].split())) or " ".join(text[span[0]:span[1]].split())
            taught = terms(line)
            if taught and entry.taught is None:
                entry.taught = taught
            elif is_address(line):
                entry.sources.append({"kind": source_kind(line.strip()), "url": line.strip()})
            else:
                entry.lines.append(line)
            attached.append((span[0], len(entries) - 1))
        positions: list[list[int]] = []
        for entry in entries:
            positions.append([])
            for values in _record_versions(entry):
                built.records.append({**values, "lines": list(entry.lines), "sources": list(entry.sources)})
                positions[-1].append(len(built.records) - 1)
        for line_start, index in attached:
            built.targets[line_start] = ("record", positions[index])

    def _highlight(self, text: str, span: tuple[int, int], text_end: int, built: _Built) -> None:
        line = _strip_bullet(" ".join(text[span[0]:text_end].split())) or " ".join(text[span[0]:span[1]].split())
        built.highlights.append({"text": line})
        built.targets[span[0]] = ("highlight", [len(built.highlights) - 1])


# --- cv-claims@1: skills a line shows, as claims ---

CV_SKILLS_SCHEMA = {
    "type": "object",
    "properties": {
        "cv_skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": list(SKILL_KINDS)},
                    "quote": {"type": "string"},
                    "level": {"type": "string", "enum": list(MODEL_LEVELS)},
                },
                "required": ["line", "name", "kind", "quote", "level"],
            },
        }
    },
    "required": ["cv_skills"],
}

CV_SKILLS_SYSTEM = """You read the numbered lines of one section of a person's CV, headed "{heading}".
List every skill the lines show the person has, one skill per entry.
A skill is one of:
- a technology, tool, platform, library, language or method (for example Python, scikit-learn, Docker, SQL)
- a research method or area of expertise the person has worked in (for example evolutionary computation,
  constrained optimisation, statistical modelling)
- a soft skill shown by what the person did (for example teaching, mentoring, technical writing)
- a degree or certification
Split lists: "Python (incl. NumPy, matplotlib)" is three skills.
Name a degree by its level and field ("PhD Computer Science"), and a certification by its name.
- "name": the skill's usual short name, 1 to 4 words.
- "kind": "technical" for technologies, tools, methods and areas of expertise; "soft" for capabilities in working
  with people; "qualification" for degrees and certifications.
- "line": the number of the line the skill comes from.
- "quote": the shortest exact text from that line that names the skill, copied character for character.
- "level": "familiar" when the line says familiar with, exposure to or basic; "expert" when it says expert or
  states long experience (8 years or more); otherwise "proficient".
Answer with JSON: {{"cv_skills": [{{"line": <number>, "name": "...", "kind": "...", "quote": "...",
"level": "..."}}]}}."""

CV_SKILLS_REMINDER = "\n\nThese lines come from a CV, so they show at least one skill. List every skill they show."


@dataclass(frozen=True)
class CvSkill:
    name: str
    kind: str
    quote: str
    level: str
    source: tuple[int, int] | None  # span of the line the model cited


class CvClaims:
    """One call per section that can hold skills (per batch of its lines), retried once when empty."""

    name = "cv-claims"
    version = 1

    def extract(self, text: str, section: Section, llm: LLM) -> list[CvSkill]:
        numbered = [f"{n}: {text[s:e]}" for n, (s, e) in enumerate(section.lines, start=1)]
        system = CV_SKILLS_SYSTEM.format(heading=section.name)
        out: list[CvSkill] = []
        for group in batches(numbered, llm.num_ctx):
            user = "\n".join(numbered[i] for i in group)
            found = self._ask(llm, system, user, section)
            if not found:
                found = self._ask(llm, system, user + CV_SKILLS_REMINDER, section)
            out.extend(found)
        return out

    def _ask(self, llm: LLM, system: str, user: str, section: Section) -> list[CvSkill]:
        response = conform("skills", llm.chat_json(system, user, CV_SKILLS_SCHEMA), CV_SKILLS_SCHEMA)
        out = []
        for entry in response["cv_skills"]:
            name = " ".join(entry["name"].split())
            if not name:
                continue
            line = entry["line"]
            source = section.lines[line - 1] if 1 <= line <= len(section.lines) else None
            out.append(CvSkill(name, entry["kind"], entry["quote"].strip(), entry["level"], source))
        return out


def _target(built: _Built, all_lines: list[tuple[int, int]], located: tuple[int, int]) -> tuple[str, list[int]] | None:
    """Where a located quote's line attaches: ("record", positions) or ("highlight", [position]); None for a line
    that suggests nothing (a heading, or a contact or summary line)."""
    for s, e in all_lines:
        if s <= located[0] < e:
            return built.targets.get(s)
    return None


def check_claims(text: str, found: list[CvSkill], built: _Built) -> list[dict]:
    """Claim suggestions, one per skill key in the order first found, each with every ground and coverage found
    and the highest level; skills whose quote isn't in the text (or is on a line that suggests nothing) go to the
    trace."""
    all_lines = lines(text)
    by_key: dict[str, dict] = {}
    for skill in found:
        located = validate.locate(text, skill.quote, skill.source)
        target = _target(built, all_lines, located) if located else None
        if target is None:
            built.unverified["skills"].append({"name": skill.name, "quote": skill.quote})
            continue
        kept = by_key.setdefault(
            name_key(skill.name), {"name": skill.name, "level": skill.level, "grounds": [], "coverage": []}
        )
        if level_rank(skill.level) > level_rank(kept["level"]):
            kept["level"] = skill.level
        quote = " ".join(text[located[0]:located[1]].split())
        kind, positions = target
        listed, ref = (kept["grounds"], "record") if kind == "record" else (kept["coverage"], "highlight")
        for position in positions:
            if all(x[ref] != position for x in listed):
                listed.append({ref: position, "quote": quote})
    return list(by_key.values())


# --- part-of@1: which record is part of which ---

# The user's guideline, word for word (design D2); it is also on the profile page's part-of form.
PART_OF_GUIDELINE = (
    "a `part_of_id` reference is made by a Record entry when the existing entry is missing important context, may "
    "be misinterpreted, or may be difficult to understand without also considering its linked Record entry"
)

PART_OF_SCHEMA = {
    "type": "object",
    "properties": {
        "part_of": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"record": {"type": "integer"}, "part_of": {"type": ["integer", "null"]}},
                "required": ["record", "part_of"],
            },
        }
    },
    "required": ["part_of"],
}

PART_OF_SYSTEM = (
    "You read the numbered records of a person's CV: roles, courses taught, projects, publications, degrees, awards "
    "and events.\n"
    "For each record, say whether it is part of another record in the list. The guideline:\n"
    f'"{PART_OF_GUIDELINE}"\n'
    "A record that stands on its own is part of no record, even when it came out of another one.\n"
    "For example (records from another CV): a conference talk that presents a paper is part of the paper's record, "
    "and a dataset released by a study is part of the study's record; a later paper that builds on the study is not.\n"
    '- "record": the number of a record.\n'
    '- "part_of": the number of the record it is part of, or null.\n'
    'Answer with JSON: {"part_of": [{"record": <number>, "part_of": <number or null>}]}.'
)


def _record_line(n: int, record: dict) -> str:
    dates = "–".join(d for d in (record["start_date"], record["end_date"]) if d) or (
        "ongoing" if record["ongoing"] else ""
    )
    first = record["lines"][0] if record["lines"] else ""
    fields = (record["kind"], record["title"] or "", record["organisation"] or "", dates, first)
    return f"{n}: " + " | ".join(fields)


class PartOf:
    """One request per run (with two records or more); answers that point at the record itself, at no record of
    the run, or make a cycle are dropped, and a record keeps its first answer."""

    name = "part-of"
    version = 1

    def links(self, records: list[dict], llm: LLM, built: _Built) -> list[dict]:
        if len(records) < 2:
            return []
        user = "\n".join(_record_line(n, r) for n, r in enumerate(records, start=1))
        response = conform("part_of", llm.chat_json(PART_OF_SYSTEM, user, PART_OF_SCHEMA), PART_OF_SCHEMA)
        parent: dict[int, int] = {}
        for answer in sorted(response["part_of"], key=lambda a: a["record"]):
            record, part_of = answer["record"] - 1, answer["part_of"]
            if part_of is None or record in parent:
                continue
            part_of -= 1
            if not (0 <= record < len(records) and 0 <= part_of < len(records)) or part_of == record:
                built.unverified["part_of"].append(answer)
                continue
            current, seen = part_of, set()
            while current in parent and current not in seen:  # would the record end up part of itself?
                seen.add(current)
                current = parent[current]
            if current == record:
                built.unverified["part_of"].append(answer)
                continue
            parent[record] = part_of
        return [{"record": r, "part_of": p} for r, p in sorted(parent.items())]


# --- The pipeline ---

SECTIONS = CapsSections()
LABELLER = LineLabeller()
RECORDS = RecordRules()
SKILLS = CvClaims()
PART_OF = PartOf()


def pipeline_id() -> str:
    return " ".join(
        f"{label}={step.name}@{step.version}"
        for label, step in (("cvseg", SECTIONS), ("cvlines", LABELLER), ("cvrecords", RECORDS), ("cvskills", SKILLS),
                            ("cvpartof", PART_OF))
    ) + f" validate={validate.NAME}@{validate.VERSION}"


def check_pipeline(pipeline: str) -> None:
    """ValueError when a queued job names a document pipeline this code no longer has."""
    if pipeline != pipeline_id():
        raise ValueError(f"pipeline {pipeline!r} is not available in this version")


def run_document(text: str, llm: LLM, should_stop: Callable[[], bool] = lambda: False) -> DocumentResult:
    """Sections, line labels, records, claims and context links, each checked against the text. Raises Cancelled
    and Unreachable; a StepFailed becomes a failed result with no suggestions."""
    started_at = datetime.now(UTC)
    trace: dict = {"steps": []}
    built = _Built()
    current = "sections"

    def step(name: str, impl) -> _Recorder:
        nonlocal current
        if should_stop():
            raise Cancelled()
        current = name
        recorder = _Recorder(llm)
        trace["steps"].append({"step": name, "name": impl.name, "version": impl.version, "calls": recorder.calls})
        return recorder

    try:
        began = time.monotonic()
        step("sections", SECTIONS)
        sections = SECTIONS.sections(text)
        trace["sections"] = [[s.name, s.kind, len(s.lines)] for s in sections]

        model = step("lines", LABELLER)
        answers: dict[int, dict] = {}
        for i, section in enumerate(sections):
            if section.kind in LABELLED_KINDS:
                if should_stop():
                    raise Cancelled()
                answers[i] = LABELLER.label(text, section, model)

        step("records", RECORDS)
        for i, section in enumerate(sections):
            if section.kind in LABELLED_KINDS or section.kind == "claims":
                RECORDS.build(text, section, answers.get(i, {}), built)

        model = step("skills", SKILLS)
        found: list[CvSkill] = []
        for section in sections:
            if section.kind in SKILL_SECTION_KINDS:
                if should_stop():
                    raise Cancelled()
                found.extend(SKILLS.extract(text, section, model))
        claims = check_claims(text, found, built)

        model = step("part_of", PART_OF)
        part_of = PART_OF.links(built.records, model, built)
        trace["seconds"] = round(time.monotonic() - began, 3)
    except StepFailed as exc:
        error = f"{exc.step or current}: {exc.message}"
        trace["error"] = error
        return DocumentResult("failed", error, started_at, datetime.now(UTC), None, trace)

    if should_stop():
        raise Cancelled()
    suggestions = {"record": built.records, "claim": claims, "part_of": part_of, "highlight": built.highlights}
    trace["unverified"] = built.unverified
    return DocumentResult("succeeded", None, started_at, datetime.now(UTC), suggestions, trace)
