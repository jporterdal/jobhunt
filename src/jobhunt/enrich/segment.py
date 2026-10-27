"""Segmenters: label each non-empty line of the description required, preferred or other."""

from __future__ import annotations

import re

from .pipeline import LABELS, LLM, Segment, conform


def lines(text: str) -> list[tuple[int, int]]:
    """(start, end) of every non-empty line, with surrounding whitespace left out."""
    spans = []
    for match in re.finditer(r"[^\n]+", text):
        raw = match.group()
        stripped = raw.strip()
        if stripped:
            start = match.start() + (len(raw) - len(raw.lstrip()))
            spans.append((start, start + len(stripped)))
    return spans


# --- rules@2 ---

_PREFERRED_HEADING = re.compile(r"preferred|nice[- ]to[- ]have|bonus|desired|ideally")
_REQUIRED_HEADING = re.compile(
    r"requirement|qualification|you['’]ll (?:need|bring)|you will (?:need|bring)|must[- ]haves?\b|you have"
    r"|responsibilit|duties|what you['’]ll do|what you will do|in this role|your role|day[- ]to[- ]day|accountabilit"
)
_INLINE_PREFERRED = re.compile(r"\ba plus\b|\bpreferred\b|nice[- ]to[- ]have")
_BULLET = re.compile(r"^(?:[-*•●▪]|\d+[.)])\s")
HEADING_MAX = 80


def is_heading(line: str) -> bool:
    """A short line with no final full stop that ends in a colon or question mark, is in title case,
    or is a few words naming a section ("Nice to have")."""
    line = line.strip()
    if not line or len(line) >= HEADING_MAX or line.endswith(".") or _BULLET.match(line):
        return False
    if line.endswith((":", "?")):
        return True
    folded = line.casefold()
    if len(line.split()) <= 5 and (_PREFERRED_HEADING.search(folded) or _REQUIRED_HEADING.search(folded)):
        return True
    words = [w for w in re.findall(r"[^\W\d_]+", line) if len(w) >= 4]
    return bool(words) and ":" not in line and all(w[0].isupper() for w in words)


class RuleSegmenter:
    """Headings start sections (duty headings start a required one); inside a required section, "a plus" or
    "nice to have" makes a line preferred."""

    name = "rules"
    version = 2

    def segment(self, text: str, llm: LLM) -> list[Segment]:
        out = []
        section = "other"
        for start, end in lines(text):
            line = text[start:end]
            folded = line.casefold()
            if is_heading(line):
                if _PREFERRED_HEADING.search(folded):
                    section = "preferred"
                elif _REQUIRED_HEADING.search(folded):
                    section = "required"
                else:
                    section = "other"
                out.append(Segment(start, end, "other"))
                continue
            label = section
            if section == "required" and _INLINE_PREFERRED.search(folded):
                label = "preferred"
            out.append(Segment(start, end, label))
        return out


# --- llm-lines@2 ---

LINES_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"line": {"type": "integer"}, "label": {"type": "string", "enum": list(LABELS)}},
                "required": ["line", "label"],
            },
        }
    },
    "required": ["lines"],
}

LINES_SYSTEM = """You label the lines of a job posting.
For each numbered line, decide what it describes:
- "required": a skill, qualification or experience the candidate must have, or work the hire will do (duty bullets
  and sentences describing the role's work)
- "preferred": a skill, qualification or experience that is a plus, nice to have, preferred or a bonus
- "other": anything else (the company, team, product, mission, benefits, pay, headings, legal text)
Answer with JSON: {"lines": [{"line": <number>, "label": "required" | "preferred" | "other"}]}.
You may leave out lines that are "other"."""

CHARS_PER_TOKEN = 3.5
BATCH_SHARE = 0.6  # of num_ctx, leaving room for instructions and the answer


def batches(numbered: list[str], num_ctx: int) -> list[list[int]]:
    """Indexes of `numbered` lines grouped so each group's estimated tokens fit in BATCH_SHARE of num_ctx."""
    budget = BATCH_SHARE * num_ctx * CHARS_PER_TOKEN
    groups: list[list[int]] = [[]]
    used = 0
    for i, line in enumerate(numbered):
        size = len(line) + 1
        if groups[-1] and used + size > budget:
            groups.append([])
            used = 0
        groups[-1].append(i)
        used += size
    return [g for g in groups if g]


class LineClassifier:
    """The model labels numbered lines; returning numbers instead of text keeps segments verbatim."""

    name = "llm-lines"
    version = 2

    def segment(self, text: str, llm: LLM) -> list[Segment]:
        spans = lines(text)
        numbered = [f"{n}: {text[s:e]}" for n, (s, e) in enumerate(spans, start=1)]
        labels = ["other"] * len(spans)
        for group in batches(numbered, llm.num_ctx):
            response = conform(
                "segment",
                llm.chat_json(LINES_SYSTEM, "\n".join(numbered[i] for i in group), LINES_SCHEMA),
                LINES_SCHEMA,
            )
            asked = {i + 1 for i in group}
            for entry in response["lines"]:
                if entry["line"] in asked:  # out-of-range numbers are ignored
                    labels[entry["line"] - 1] = entry["label"]
        return [Segment(s, e, label) for (s, e), label in zip(spans, labels, strict=True)]


SEGMENTERS = (LineClassifier(), RuleSegmenter())
DEFAULT_SEGMENTER = LineClassifier.name
