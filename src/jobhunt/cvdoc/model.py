"""A CV's content and its laid-out form (design D1, D4). No database, no Flask.

The **content** is what to print, as frozen field values: `{"produced": "2026-10-16", "left_out": [kind, ...],
"items": [{"section", "source_kind", "source_id", "payload"}, ...]}`, items in print order within their section.
A proposal (tailor.py) and a saved CV (queries.tailored_cv) both give one; `layout.build` turns it into a `Cv`,
which the HTML preview and the ODT writer render.

Payloads at CONTENT_VERSION 1, by source_kind:
- detail: {kind, label, text}
- highlight: {text}
- record: {id, kind, title, organisation, location, start_date, end_date, ongoing, lines: [text], sources: [url],
  context: {title, organisation} | None, children: [record or course group payload]}
- course_group: the record fields without id, start_date, end_date and ongoing, plus terms: [{start_date,
  end_date, ongoing}] and record_ids: [id]
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CONTENT_VERSION = 1


@dataclass(frozen=True)
class Header:
    name: str | None
    headline: str | None
    produced: str  # "October 2026"
    contacts: tuple[str, ...]  # labelled: "Email: someone@example.com"


@dataclass(frozen=True)
class Paragraph:
    text: str


@dataclass(frozen=True)
class Bullet:
    text: str


@dataclass(frozen=True)
class Entry:
    title: str
    subtitle: str | None  # organisation and location
    dates: str | None
    lines: tuple[str, ...]
    sources: tuple[str, ...]
    context_note: str | None  # "Part of: ..." when its context record isn't printed
    children: tuple[Entry, ...]


Block = Paragraph | Bullet | Entry


@dataclass(frozen=True)
class Section:
    key: str  # 'goal', 'summary', 'highlights' or a record kind
    heading: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Cv:
    header: Header
    sections: tuple[Section, ...]


def is_course_group(payload: dict) -> bool:
    return "terms" in payload


def content_to_json(payload: dict) -> str:
    """A payload as stored in tailored_cv_items.payload_json."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_from_json(text: str, version: int = CONTENT_VERSION) -> dict:
    """A stored payload. Every version written so far is read; there is only version 1."""
    if version != CONTENT_VERSION:
        raise ValueError(f"unknown CV content version {version}")
    return json.loads(text)
