"""Write captures, postings and snapshots; history is added to, never rewritten."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Row

from .db import captures, posting_snapshots, postings
from .parsers import ParsedPosting
from .sanitize import clean_html, html_to_text

SOURCE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
MAX_SOURCE, MAX_EXTERNAL_ID = 100, 200

# The core fields compared to decide whether a re-capture changed the posting; the details are compared too.
# The posted date and the volatile details change on every visit, so they are stored but not compared.
CORE_FIELDS = (
    "title",
    "company",
    "location",
    "workplace_type",
    "employment_type",
    "description_html",
    "description_text",
)


class InvalidPosting(ValueError):
    """A parser returned a posting the store can't keep; the importer reports it as that parser's error."""


@dataclass(frozen=True)
class Stored:
    outcome: str  # 'new', 'updated' or 'unchanged'
    job_id: int


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_value(value) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value)


def canonical_details(details: Mapping) -> dict:
    """Details without null, "" and [] values, keys sorted; a value of another kind is refused."""
    out = {}
    for name in sorted(details, key=str):
        value = details[name]
        if not isinstance(name, str) or not name:
            raise InvalidPosting(f"detail name {name!r} must be non-empty text")
        if not _is_value(value):
            raise InvalidPosting(f"detail {name!r} must be text, a number, true or false, or a list of text")
        if isinstance(value, tuple):
            value = list(value)
        if value is None or value == "" or value == []:
            continue
        out[name] = value
    return out


def fingerprint(core: Mapping, details: Mapping) -> str:
    """SHA-256 of the compared content: the core fields (CORE_FIELDS) and the canonical details."""
    values = [core[name] for name in CORE_FIELDS] + [canonical_details(details)]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def find_capture(conn: Connection, sha256: str) -> Row | None:
    return conn.execute(select(captures.c.id, captures.c.job_id).where(captures.c.sha256 == sha256)).first()


def latest_snapshot(conn: Connection, job_id: int) -> Row | None:
    return conn.execute(
        select(posting_snapshots)
        .where(posting_snapshots.c.job_id == job_id)
        .order_by(posting_snapshots.c.id.desc())
        .limit(1)
    ).first()


def _required(posting: ParsedPosting) -> None:
    if not SOURCE.fullmatch(posting.source or "") or len(posting.source) > MAX_SOURCE:
        raise InvalidPosting(f"source {posting.source!r} must be lowercase letters, digits, dots and hyphens")
    if not (posting.external_id or "").strip() or len(posting.external_id) > MAX_EXTERNAL_ID:
        raise InvalidPosting(f"external ID {posting.external_id!r} must be 1 to {MAX_EXTERNAL_ID} characters")
    for name in ("url", "title", "company"):
        if not (getattr(posting, name) or "").strip():
            raise InvalidPosting(f"the posting has no {name}")
    if urlsplit(posting.url.strip()).scheme.lower() not in ("http", "https"):
        raise InvalidPosting(f"URL {posting.url!r} must be an http or https address")


def store_capture(
    conn: Connection,
    posting: ParsedPosting,
    raw: bytes,
    source_name: str,
    modified_at: datetime,
    imported_at: datetime,
    parser: str,
) -> Stored:
    """Record one accepted file. `parser` is the accepting parser's "name@version".

    The capture time is the one the parser reports, else `modified_at` (the file's). The description HTML is
    sanitized here, whichever parser produced it, and its text derived when the parser gives none. The caller
    owns the transaction and must already have checked find_capture().
    """
    _required(posting)
    description_html = clean_html(posting.description_html)
    description_text = (
        posting.description_text if posting.description_text is not None else html_to_text(description_html)
    )
    if not description_text.strip():
        raise InvalidPosting("the description is empty")
    details = canonical_details(posting.details)
    volatile = canonical_details(posting.volatile_details)
    captured_at = posting.captured_at or modified_at

    existing = conn.execute(
        select(postings).where(postings.c.source == posting.source, postings.c.external_id == posting.external_id)
    ).first()
    if existing is None:
        job_id = conn.execute(
            postings.insert().values(
                source=posting.source,
                external_id=posting.external_id,
                url=posting.url,
                first_seen_at=captured_at,
                last_seen_at=captured_at,
            )
        ).inserted_primary_key[0]
    else:
        job_id = existing.job_id
        # Out-of-order imports must never move first-seen later or last-seen earlier.
        conn.execute(
            update(postings)
            .where(postings.c.job_id == job_id)
            .values(
                first_seen_at=min(existing.first_seen_at, captured_at),
                last_seen_at=max(existing.last_seen_at, captured_at),
            )
        )

    capture_id = conn.execute(
        captures.insert().values(
            sha256=sha256_hex(raw),
            job_id=job_id,
            source_name=source_name,
            captured_at=captured_at,
            imported_at=imported_at,
            raw_gz=gzip.compress(raw),
            parser=parser,
        )
    ).inserted_primary_key[0]

    core = {
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "workplace_type": posting.workplace_type,
        "employment_type": posting.employment_type,
        "description_html": description_html,
        "description_text": description_text,
    }
    current = fingerprint(core, details)
    latest = latest_snapshot(conn, job_id)
    if latest is not None and latest.fingerprint == current:
        return Stored("unchanged", job_id)

    conn.execute(
        posting_snapshots.insert().values(
            job_id=job_id,
            capture_id=capture_id,
            parser=parser,
            fingerprint=current,
            **core,
            posted_on_estimate=posting.posted_on,
            posted_on_precision=posting.posted_precision or ("day" if posting.posted_on else None),
            details_json=json.dumps(details, ensure_ascii=False),
            volatile_json=json.dumps(volatile, ensure_ascii=False),
        )
    )
    return Stored("new" if existing is None else "updated", job_id)


def read_capture(conn: Connection, capture_id: int) -> bytes:
    """The original bytes of a stored capture."""
    raw_gz = conn.execute(select(captures.c.raw_gz).where(captures.c.id == capture_id)).scalar_one()
    return gzip.decompress(raw_gz)
