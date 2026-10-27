"""Every write of user-authored data. The caller owns the transaction; no HTML, no Flask.

store.py writes captured data and never touches these tables; this module never writes captured tables.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime

from bs4 import BeautifulSoup
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Row
from sqlalchemy.sql.schema import Table

from .db import (
    app_settings,
    application_contacts,
    application_documents,
    application_events,
    applications,
    claim_records,
    claims,
    companies,
    contact_emails,
    contacts,
    dismiss_reasons,
    documents,
    enrichment_skills,
    highlight_claims,
    highlights,
    posting_dismissal_reasons,
    posting_dismissals,
    posting_enrichments,
    posting_skill_marks,
    posting_tags,
    posting_triage,
    postings,
    profile_details,
    profile_rejections,
    record_lines,
    record_sources,
    records,
    rejected_suggestions,
    skill_aliases,
    skill_link_overrides,
    skills,
    tags,
    tailored_cv_items,
    tailored_cvs,
)
from .store import latest_snapshot

RATING_FIELDS = ("interest", "fit")
SKILL_LEVELS = ("missing", "learning", "familiar", "proficient", "expert")  # an ordered scale, lowest first
MODEL_LEVELS = ("familiar", "proficient", "expert")  # what document extraction may suggest
RECORD_KINDS = ("role", "course", "project", "publication", "degree", "award", "event", "task", "other")
DETAIL_KINDS = ("name", "headline", "contact", "summary", "goal")  # shown in this order
SOURCE_KINDS = ("repo", "site", "doi", "document", "other")
DISCLOSURES = ("public", "private")
LINK_RELATIONS = ("same", "specific", "general", "related")  # strongest first, from the profile skill's side
# Application statuses in pipeline order; an event can also be a plain "note".
OPEN_STATUSES = ("interested", "applied", "screening", "interviewing", "offer")
CLOSED_STATUSES = ("accepted", "rejected", "ghosted", "withdrawn")
STATUSES = OPEN_STATUSES + CLOSED_STATUSES
EVENT_KINDS = STATUSES + ("note",)
NO_EVENT_STATUS = "interested"
DOCUMENT_KINDS = ("cv", "cover_letter", "other")
MARK_IMPORTANCES = ("required", "preferred")
MARK_ORIGINS = ("selection", "suggestion")
REJECTION_REASONS = ("not-a-skill", "not-for-me")
NUM_CTX_RANGE = (2048, 131072)
DEFAULT_SETTINGS = {
    "llm.model": None,
    "llm.num_ctx": 8192,
    "llm.segmenter": "llm-lines",
    "llm.embed_model": None,  # None: an installed nomic-embed-text (links.embed_model)
    "eval.holdout_start": None,  # postings first flagged complete after this are held out of development
    "demo.created_at": None,  # set only by `jobhunt demo`: the database holds demo data
}


class UserDataError(ValueError):
    """A request the user can fix: bad rating, empty name, posting already dismissed, ..."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def collapse(text: str) -> str:
    return " ".join(text.split())


def name_key(name: str) -> str:
    """Identity of a tag, skill, company or dismiss reason: trimmed, spaces collapsed, casefolded.

    Done in Python rather than SQL so it behaves the same on SQLite (whose lower() is ASCII-only).
    """
    return collapse(name).casefold()


def _optional(text: str | None) -> str | None:
    return (text or "").strip() or None


def _clean_name(name: str) -> str:
    cleaned = collapse(name)
    if not cleaned:
        raise UserDataError("name must not be empty")
    return cleaned


def _get_or_create(conn: Connection, table: Table, name: str, **extra) -> Row:
    """The row whose key matches `name`, created with `name` as typed if there is none."""
    name = _clean_name(name)
    key = name_key(name)
    row = conn.execute(select(table).where(table.c.key == key)).first()
    if row is None:
        conn.execute(insert(table).values(name=name, key=key, **extra))
        row = conn.execute(select(table).where(table.c.key == key)).one()
    return row


def get_or_create_tag(conn: Connection, name: str) -> Row:
    return _get_or_create(conn, tags, name)


def get_or_create_skill(conn: Connection, name: str, now: datetime | None = None) -> Row:
    return _get_or_create(conn, skills, name, updated_at=now or utcnow())


# --- Triage: ratings, notes, tags ---


def _touch_triage(conn: Connection, job_id: int, now: datetime, **values) -> None:
    exists = conn.execute(select(posting_triage.c.job_id).where(posting_triage.c.job_id == job_id)).first()
    if exists is None:
        conn.execute(insert(posting_triage).values(job_id=job_id, updated_at=now, **values))
    else:
        conn.execute(
            update(posting_triage).where(posting_triage.c.job_id == job_id).values(updated_at=now, **values)
        )


def set_rating(conn: Connection, job_id: int, field: str, value: int | None, now: datetime | None = None) -> None:
    """Set interest or fit to 1-5, or clear it with None."""
    if field not in RATING_FIELDS:
        raise UserDataError(f"unknown rating {field!r}")
    if value is not None and not (isinstance(value, int) and 1 <= value <= 5):
        raise UserDataError("ratings run from 1 to 5")
    _touch_triage(conn, job_id, now or utcnow(), **{field: value})


def set_notes(conn: Connection, job_id: int, notes: str | None, now: datetime | None = None) -> None:
    notes = (notes or "").strip() or None
    _touch_triage(conn, job_id, now or utcnow(), notes=notes)


def add_tag(conn: Connection, job_id: int, name: str, now: datetime | None = None) -> Row:
    """Tag the posting, reusing a tag with the same key. Adding a tag it already has does nothing."""
    tag = get_or_create_tag(conn, name)
    already = conn.execute(
        select(posting_tags).where(posting_tags.c.job_id == job_id, posting_tags.c.tag_id == tag.id)
    ).first()
    if already is None:
        conn.execute(insert(posting_tags).values(job_id=job_id, tag_id=tag.id, created_at=now or utcnow()))
    return tag


def remove_tag(conn: Connection, job_id: int, tag_id: int) -> None:
    conn.execute(delete(posting_tags).where(posting_tags.c.job_id == job_id, posting_tags.c.tag_id == tag_id))


# --- Dismissals ---


def open_dismissal(conn: Connection, job_id: int) -> Row | None:
    return conn.execute(
        select(posting_dismissals).where(
            posting_dismissals.c.job_id == job_id, posting_dismissals.c.restored_at.is_(None)
        )
    ).first()


def dismiss(
    conn: Connection,
    job_id: int,
    reason_ids: list[int],
    comment: str | None = None,
    now: datetime | None = None,
) -> int:
    """Dismiss a posting for one or more reasons. A posting has at most one open dismissal."""
    reason_ids = sorted(set(reason_ids))
    if not reason_ids:
        raise UserDataError("choose at least one reason")
    known = set(conn.execute(select(dismiss_reasons.c.id).where(dismiss_reasons.c.id.in_(reason_ids))).scalars())
    if known != set(reason_ids):
        raise UserDataError("unknown dismiss reason")
    if open_dismissal(conn, job_id) is not None:
        raise UserDataError("posting is already dismissed")
    dismissal_id = conn.execute(
        insert(posting_dismissals).values(
            job_id=job_id, dismissed_at=now or utcnow(), comment=(comment or "").strip() or None
        )
    ).inserted_primary_key[0]
    conn.execute(
        insert(posting_dismissal_reasons),
        [{"dismissal_id": dismissal_id, "reason_id": reason_id} for reason_id in reason_ids],
    )
    return dismissal_id


def restore(conn: Connection, job_id: int, now: datetime | None = None) -> None:
    """End the open dismissal. The row and its reasons stay as history."""
    current = open_dismissal(conn, job_id)
    if current is None:
        raise UserDataError("posting is not dismissed")
    conn.execute(
        update(posting_dismissals).where(posting_dismissals.c.id == current.id).values(restored_at=now or utcnow())
    )


def add_dismiss_reason(conn: Connection, label: str) -> Row:
    """A new reason at the end of the list, or the existing one with the same key."""
    label = _clean_name(label)
    key = name_key(label)
    row = conn.execute(select(dismiss_reasons).where(dismiss_reasons.c.key == key)).first()
    if row is None:
        position = conn.execute(select(func.coalesce(func.max(dismiss_reasons.c.position), 0))).scalar_one() + 1
        conn.execute(insert(dismiss_reasons).values(label=label, key=key, position=position))
        row = conn.execute(select(dismiss_reasons).where(dismiss_reasons.c.key == key)).one()
    return row


# --- Skills ---


def add_skill_mark(
    conn: Connection,
    job_id: int,
    skill_name: str,
    quote: str,
    now: datetime | None = None,
    importance: str | None = None,
    origin: str = "selection",
) -> int:
    """Record that the posting asks for a skill, quoting the text the user selected in its latest snapshot."""
    quote = collapse(quote)
    if not quote:
        raise UserDataError("select some description text to mark")
    _check_importance(importance)
    if origin not in MARK_ORIGINS:
        raise UserDataError(f"origin must be one of {', '.join(MARK_ORIGINS)}")
    snapshot = latest_snapshot(conn, job_id)
    if snapshot is None:
        raise UserDataError("posting has no snapshot to mark")
    now = now or utcnow()
    skill = get_or_create_skill(conn, skill_name, now)
    mark_id = conn.execute(
        insert(posting_skill_marks).values(
            job_id=job_id,
            skill_id=skill.id,
            quote=quote,
            snapshot_id=snapshot.id,
            created_at=now,
            importance=importance,
            origin=origin,
        )
    ).inserted_primary_key[0]
    skills_changed(conn)
    return mark_id


def _check_importance(importance: str | None) -> None:
    if importance is not None and importance not in MARK_IMPORTANCES:
        raise UserDataError(f"importance must be one of {', '.join(MARK_IMPORTANCES)}")


def set_mark_importance(conn: Connection, mark_id: int, importance: str | None) -> None:
    """Required, preferred, or None for unspecified. The quote and origin stay as they are."""
    _check_importance(importance)
    conn.execute(update(posting_skill_marks).where(posting_skill_marks.c.id == mark_id).values(importance=importance))


def remove_skill_mark(conn: Connection, mark_id: int) -> None:
    conn.execute(delete(posting_skill_marks).where(posting_skill_marks.c.id == mark_id))
    skills_changed(conn)


def set_skills_complete(conn: Connection, job_id: int, complete: bool, now: datetime | None = None) -> None:
    """Flag that every skill the posting asks for is marked (it joins the labelled set), or clear the flag."""
    if conn.execute(select(postings.c.job_id).where(postings.c.job_id == job_id)).first() is None:
        raise UserDataError("no such posting")
    now = now or utcnow()
    first = conn.execute(
        select(posting_triage.c.skills_first_complete_at).where(posting_triage.c.job_id == job_id)
    ).scalar()
    values = {"skills_complete_at": now if complete else None}
    if complete and first is None:
        values["skills_first_complete_at"] = now  # never cleared: it decides development or held-out
    _touch_triage(conn, job_id, now, **values)


def matchable_text(description_html: str) -> str:
    """Description text as the user can select it: tags dropped, whitespace collapsed, casefolded."""
    return collapse(BeautifulSoup(description_html, "lxml").get_text(" ")).casefold()


def quote_found(quote: str, description_html: str) -> bool:
    return collapse(quote).casefold() in matchable_text(description_html)


# --- Model suggestions (derived rows are read here, never written) ---


def _check_reason(reason: str) -> None:
    if reason not in REJECTION_REASONS:
        raise UserDataError(f"reason must be one of {', '.join(REJECTION_REASONS)}")


def _rejection(key: str, job_id: int):
    return (rejected_suggestions.c.job_id == job_id) & (rejected_suggestions.c.skill_key == key)


def reject_suggestion(
    conn: Connection, job_id: int, skill_name: str, reason: str, now: datetime | None = None
) -> None:
    """Hide a suggested skill for this posting in every run, later ones too, until it is unrejected.
    `reason` is 'not-a-skill' or 'not-for-me'; rejecting it again changes the reason."""
    _check_reason(reason)
    key = name_key(_clean_name(skill_name))
    if conn.execute(select(rejected_suggestions).where(_rejection(key, job_id))).first() is None:
        conn.execute(
            insert(rejected_suggestions).values(job_id=job_id, skill_key=key, reason=reason, created_at=now or utcnow())
        )
        skills_changed(conn)
    else:
        conn.execute(update(rejected_suggestions).where(_rejection(key, job_id)).values(reason=reason))


def set_rejection_reason(conn: Connection, job_id: int, skill_name: str, reason: str) -> None:
    """Give or change the reason of an existing rejection, including one made before reasons existed."""
    _check_reason(reason)
    key = name_key(skill_name)
    if conn.execute(update(rejected_suggestions).where(_rejection(key, job_id)).values(reason=reason)).rowcount == 0:
        raise UserDataError("that suggestion is not rejected")


def unreject_suggestion(conn: Connection, job_id: int, skill_name: str) -> None:
    removed = conn.execute(
        delete(rejected_suggestions).where(
            rejected_suggestions.c.job_id == job_id, rejected_suggestions.c.skill_key == name_key(skill_name)
        )
    ).rowcount
    if removed:
        skills_changed(conn)


def _marked_keys(conn: Connection, job_id: int) -> set[str]:
    return set(
        conn.execute(
            select(skills.c.key)
            .join(posting_skill_marks, posting_skill_marks.c.skill_id == skills.c.id)
            .where(posting_skill_marks.c.job_id == job_id)
        ).scalars()
    )


def _acceptable_run(conn: Connection, enrichment_id: int, job_id: int | None = None) -> tuple[Row, Row]:
    """(run, latest snapshot) when suggestions from the run may be accepted, else UserDataError."""
    run = conn.execute(select(posting_enrichments).where(posting_enrichments.c.id == enrichment_id)).first()
    if run is None or (job_id is not None and run.job_id != job_id):
        raise UserDataError("no such extraction run")
    if run.origin != "app":
        raise UserDataError("the run is not one the app uses (jobhunt eval made it)")
    if run.status != "succeeded":
        raise UserDataError("the extraction run failed, so it has nothing to accept")
    snapshot = latest_snapshot(conn, run.job_id)
    if snapshot is None or snapshot.id != run.snapshot_id:
        raise UserDataError("the run was made on an older snapshot; extract the current one first")
    return run, snapshot


def _accept(conn: Connection, item: Row, run: Row, snapshot: Row, now: datetime) -> int:
    # The mark quotes the description itself, not the model's copy, so it highlights like a selection.
    quote = snapshot.description_text[item.start_offset:item.end_offset]
    return add_skill_mark(
        conn, run.job_id, item.name, quote, now, importance=item.importance, origin="suggestion"
    )


def accept_suggestion(conn: Connection, enrichment_skill_id: int, now: datetime | None = None) -> int:
    """Copy a verified suggestion from a run on the latest snapshot into a skill mark with origin suggestion."""
    item = conn.execute(select(enrichment_skills).where(enrichment_skills.c.id == enrichment_skill_id)).first()
    if item is None:
        raise UserDataError("no such suggestion")
    if not item.verified:
        raise UserDataError("the suggestion's quote is not in the description, so it cannot be accepted")
    run, snapshot = _acceptable_run(conn, item.enrichment_id)
    if item.key in _marked_keys(conn, run.job_id):
        raise UserDataError(f"the posting already marks {item.name}")
    return _accept(conn, item, run, snapshot, now or utcnow())


def accept_all(conn: Connection, job_id: int, enrichment_id: int, importance: str, now: datetime | None = None) -> int:
    """Accept every verified, unrejected suggestion of one importance not already marked; the number accepted."""
    if importance not in MARK_IMPORTANCES:
        raise UserDataError(f"importance must be one of {', '.join(MARK_IMPORTANCES)}")
    run, snapshot = _acceptable_run(conn, enrichment_id, job_id)
    skip = _marked_keys(conn, job_id) | set(
        conn.execute(select(rejected_suggestions.c.skill_key).where(rejected_suggestions.c.job_id == job_id)).scalars()
    )
    now = now or utcnow()
    accepted = 0
    for item in conn.execute(
        select(enrichment_skills)
        .where(
            enrichment_skills.c.enrichment_id == run.id,
            enrichment_skills.c.importance == importance,
            enrichment_skills.c.verified.is_(True),
        )
        .order_by(enrichment_skills.c.position)
    ).all():
        if item.key not in skip:
            _accept(conn, item, run, snapshot, now)
            skip.add(item.key)
            accepted += 1
    return accepted


# --- Settings ---


def get_setting(conn: Connection, key: str):
    """The stored value, typed, or the default."""
    if key not in DEFAULT_SETTINGS:
        raise UserDataError(f"unknown setting {key!r}")
    value = conn.execute(select(app_settings.c.value).where(app_settings.c.key == key)).scalar()
    if not value:
        return DEFAULT_SETTINGS[key]
    if key == "llm.num_ctx":
        return int(value)
    if key in ("eval.holdout_start", "demo.created_at"):
        return datetime.fromisoformat(value)
    return value


def settings(conn: Connection) -> dict:
    return {key: get_setting(conn, key) for key in DEFAULT_SETTINGS}


def set_setting(conn: Connection, key: str, value, now: datetime | None = None) -> None:
    if key == "llm.model":
        value = (value or "").strip()
        if not value:
            raise UserDataError("choose a model")
    elif key == "llm.num_ctx":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise UserDataError("the context size must be a whole number") from None
        low, high = NUM_CTX_RANGE
        if not low <= value <= high:
            raise UserDataError(f"the context size must be from {low} to {high}")
    elif key == "llm.segmenter":
        from .enrich.pipeline import segmenters

        if value not in segmenters():
            raise UserDataError(f"segmenter must be one of {', '.join(segmenters())}")
    elif key == "llm.embed_model":
        value = (value or "").strip()
        if not value:
            raise UserDataError("choose an embedding model")
    elif key == "eval.holdout_start":
        value = _holdout_start(value)
    elif key == "demo.created_at":
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise UserDataError("the demo's creation time must be a date and time with a time zone")
        value = value.astimezone(UTC).isoformat()
    else:
        raise UserDataError(f"unknown setting {key!r}")
    now = now or utcnow()
    stored = str(value)
    previous = conn.execute(select(app_settings.c.value).where(app_settings.c.key == key)).first()
    if previous is None:
        conn.execute(insert(app_settings).values(key=key, value=stored, updated_at=now))
    else:
        conn.execute(update(app_settings).where(app_settings.c.key == key).values(value=stored, updated_at=now))
    if key == "llm.embed_model" and (previous is None or previous.value != stored):
        skills_changed(conn)  # candidates are shortlisted with this model: re-judge with the new one


def _holdout_start(value) -> str:
    """A timezone-aware time (or ISO string) as a UTC ISO string; None or empty clears the start."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            raise UserDataError("the held-out start must be a date and time") from None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise UserDataError("the held-out start must be a date and time with a time zone")
    return value.astimezone(UTC).isoformat()


# --- Applications ---


def _application(conn: Connection, app_id: int) -> Row:
    row = conn.execute(select(applications).where(applications.c.id == app_id)).first()
    if row is None:
        raise UserDataError("no such application")
    return row


def _posting_application_id(conn: Connection, job_id: int) -> int | None:
    return conn.execute(select(applications.c.id).where(applications.c.job_id == job_id)).scalar()


def start_application(conn: Connection, job_id: int, now: datetime | None = None) -> int:
    """An application for a posting, with title, company and URL copied from it. A posting has at most one;
    starting again returns the existing one."""
    existing = _posting_application_id(conn, job_id)
    if existing is not None:
        return existing
    posting = conn.execute(select(postings).where(postings.c.job_id == job_id)).first()
    snapshot = latest_snapshot(conn, job_id)
    if posting is None or snapshot is None:
        raise UserDataError("no such posting")
    now = now or utcnow()
    return conn.execute(
        insert(applications).values(
            job_id=job_id,
            title=snapshot.title,
            company=snapshot.company,
            url=posting.url,
            status=NO_EVENT_STATUS,
            created_at=now,
            updated_at=now,
        )
    ).inserted_primary_key[0]


def create_application(
    conn: Connection, title: str, company: str, url: str | None = None, now: datetime | None = None
) -> int:
    """An application entered by hand, for a job with no stored posting."""
    title, company = collapse(title), collapse(company)
    if not title or not company:
        raise UserDataError("an application needs a job title and a company")
    now = now or utcnow()
    return conn.execute(
        insert(applications).values(
            title=title, company=company, url=_optional(url), status=NO_EVENT_STATUS, created_at=now, updated_at=now
        )
    ).inserted_primary_key[0]


def link_application(conn: Connection, app_id: int, job_id: int, now: datetime | None = None) -> None:
    """Attach a manual application to a posting that has none. Events, documents and contacts stay."""
    app = _application(conn, app_id)
    if app.job_id is not None:
        raise UserDataError("application is already linked to a posting")
    if conn.execute(select(postings.c.job_id).where(postings.c.job_id == job_id)).first() is None:
        raise UserDataError("no such posting")
    if _posting_application_id(conn, job_id) is not None:
        raise UserDataError("that posting already has an application")
    conn.execute(
        update(applications).where(applications.c.id == app_id).values(job_id=job_id, updated_at=now or utcnow())
    )


def update_application(
    conn: Connection,
    app_id: int,
    title: str,
    company: str,
    url: str | None,
    compensation_notes: str | None,
    now: datetime | None = None,
) -> None:
    _application(conn, app_id)
    title, company = collapse(title), collapse(company)
    if not title or not company:
        raise UserDataError("an application needs a job title and a company")
    conn.execute(
        update(applications)
        .where(applications.c.id == app_id)
        .values(
            title=title,
            company=company,
            url=_optional(url),
            compensation_notes=_optional(compensation_notes),
            updated_at=now or utcnow(),
        )
    )


def set_next_action(
    conn: Connection, app_id: int, text: str | None, due: date | None, now: datetime | None = None
) -> None:
    _application(conn, app_id)
    text = _optional(text)
    conn.execute(
        update(applications)
        .where(applications.c.id == app_id)
        .values(next_action=text, next_action_due=due if text else None, updated_at=now or utcnow())
    )


def add_event(
    conn: Connection,
    app_id: int,
    kind: str,
    event_date: date,
    note: str | None = None,
    now: datetime | None = None,
) -> int:
    """Append a dated event. Events are never edited; the status is recomputed from them."""
    if kind not in EVENT_KINDS:
        raise UserDataError(f"unknown event kind {kind!r}")
    _application(conn, app_id)
    event_id = conn.execute(
        insert(application_events).values(
            application_id=app_id, kind=kind, event_date=event_date, note=_optional(note), created_at=now or utcnow()
        )
    ).inserted_primary_key[0]
    recompute_status(conn, app_id, now)
    return event_id


def delete_event(conn: Connection, app_id: int, event_id: int) -> None:
    """Remove a mistaken event, then recompute the status."""
    conn.execute(
        delete(application_events).where(
            application_events.c.id == event_id, application_events.c.application_id == app_id
        )
    )
    recompute_status(conn, app_id)


def status_from_events(conn: Connection, app_id: int) -> tuple[str, date | None]:
    """The kind and date of the latest non-note event (by date, then entry order), or interested."""
    latest = conn.execute(
        select(application_events.c.kind, application_events.c.event_date)
        .where(application_events.c.application_id == app_id, application_events.c.kind != "note")
        .order_by(application_events.c.event_date.desc(), application_events.c.id.desc())
        .limit(1)
    ).first()
    return (latest.kind, latest.event_date) if latest else (NO_EVENT_STATUS, None)


def recompute_status(conn: Connection, app_id: int, now: datetime | None = None) -> None:
    """The only writer of the cached applications.status and status_date."""
    status, status_date = status_from_events(conn, app_id)
    conn.execute(
        update(applications)
        .where(applications.c.id == app_id)
        .values(status=status, status_date=status_date, updated_at=now or utcnow())
    )


# --- Documents (metadata; the bytes are stored by documents.py) ---


def add_document(conn: Connection, stored, label: str, kind: str, now: datetime | None = None) -> int:
    """Record an uploaded file. `stored` is a documents.StoredFile."""
    if kind not in DOCUMENT_KINDS:
        raise UserDataError(f"kind must be one of {', '.join(DOCUMENT_KINDS)}")
    label = collapse(label) or stored.original_filename
    return conn.execute(
        insert(documents).values(
            sha256=stored.sha256,
            label=label,
            kind=kind,
            original_filename=stored.original_filename,
            media_type=stored.media_type,
            size_bytes=stored.size_bytes,
            uploaded_at=now or utcnow(),
            text_content=stored.text_content,
            text_status=stored.text_status,
        )
    ).inserted_primary_key[0]


def link_document(conn: Connection, app_id: int, document_id: int) -> None:
    _application(conn, app_id)
    if conn.execute(select(documents.c.id).where(documents.c.id == document_id)).first() is None:
        raise UserDataError("no such document")
    linked = conn.execute(
        select(application_documents).where(
            application_documents.c.application_id == app_id, application_documents.c.document_id == document_id
        )
    ).first()
    if linked is None:
        conn.execute(insert(application_documents).values(application_id=app_id, document_id=document_id))


def unlink_document(conn: Connection, app_id: int, document_id: int) -> None:
    conn.execute(
        delete(application_documents).where(
            application_documents.c.application_id == app_id, application_documents.c.document_id == document_id
        )
    )


# --- Companies and contacts ---


def get_or_create_company(conn: Connection, name: str, now: datetime | None = None) -> Row:
    now = now or utcnow()
    return _get_or_create(conn, companies, name, created_at=now, updated_at=now)


def update_company(
    conn: Connection,
    company_id: int,
    name: str,
    website_url: str | None,
    careers_url: str | None,
    notes: str | None,
    now: datetime | None = None,
) -> None:
    name = _clean_name(name)
    key = name_key(name)
    clash = conn.execute(select(companies.c.id).where(companies.c.key == key, companies.c.id != company_id)).first()
    if clash is not None:
        raise UserDataError(f"a company named {name!r} already exists")
    conn.execute(
        update(companies)
        .where(companies.c.id == company_id)
        .values(
            name=name,
            key=key,
            website_url=_optional(website_url),
            careers_url=_optional(careers_url),
            notes=_optional(notes),
            updated_at=now or utcnow(),
        )
    )


def _clean_emails(emails: list[str]) -> list[str]:
    seen, out = set(), []
    for email in emails:
        email = email.strip()
        if email and email.casefold() not in seen:
            seen.add(email.casefold())
            out.append(email)
    return out


def save_contact(
    conn: Connection,
    contact_id: int | None,
    name: str,
    emails: list[str],
    role: str | None = None,
    profile_url: str | None = None,
    notes: str | None = None,
    company_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Create a contact (contact_id None) or replace an existing one's fields and email list."""
    name = collapse(name)
    if not name:
        raise UserDataError("a contact needs a name")
    if (
        company_id is not None
        and conn.execute(select(companies.c.id).where(companies.c.id == company_id)).first() is None
    ):
        raise UserDataError("no such company")
    now = now or utcnow()
    values = dict(
        name=name, role=_optional(role), profile_url=_optional(profile_url), notes=_optional(notes),
        company_id=company_id, updated_at=now,
    )
    if contact_id is None:
        contact_id = conn.execute(insert(contacts).values(created_at=now, **values)).inserted_primary_key[0]
    else:
        if conn.execute(select(contacts.c.id).where(contacts.c.id == contact_id)).first() is None:
            raise UserDataError("no such contact")
        conn.execute(update(contacts).where(contacts.c.id == contact_id).values(**values))
        conn.execute(delete(contact_emails).where(contact_emails.c.contact_id == contact_id))
    cleaned = _clean_emails(emails)
    if cleaned:
        conn.execute(insert(contact_emails), [{"contact_id": contact_id, "email": e} for e in cleaned])
    return contact_id


def link_contact(conn: Connection, app_id: int, contact_id: int) -> None:
    _application(conn, app_id)
    if conn.execute(select(contacts.c.id).where(contacts.c.id == contact_id)).first() is None:
        raise UserDataError("no such contact")
    linked = conn.execute(
        select(application_contacts).where(
            application_contacts.c.application_id == app_id, application_contacts.c.contact_id == contact_id
        )
    ).first()
    if linked is None:
        conn.execute(insert(application_contacts).values(application_id=app_id, contact_id=contact_id))


def unlink_contact(conn: Connection, app_id: int, contact_id: int) -> None:
    conn.execute(
        delete(application_contacts).where(
            application_contacts.c.application_id == app_id, application_contacts.c.contact_id == contact_id
        )
    )


# --- The profile: a knowledge base CVs are built from ---
#
# Records are facts, a claim holds a skill's level, grounds tie a claim to the records that show it, highlights
# are CV wording covering claims, aliases send a merged skill to the one it was merged into, and details are the
# name, headline, contact lines, summaries and goals. Rows are 'user', 'suggestion' or 'model' (db.records); a
# content edit makes a row the user's, moving it doesn't. Deleting a row, or editing it so its identity changes,
# remembers the old identity (profile_rejections), so document suggestions with it aren't offered again; adding
# the same thing by hand forgets it.

_PARTIAL_DATE = re.compile(r"\d{4}(-(0[1-9]|1[0-2]))?")
LABEL_CHARS = 120


def skills_changed(conn: Connection) -> None:
    """Profile skills or posting skills changed: queue link judging (enrich/jobs.py writes the queue)."""
    from .enrich.jobs import enqueue_links

    enqueue_links(conn)


def level_rank(level: str | None) -> int:
    return SKILL_LEVELS.index(level) if level in SKILL_LEVELS else -1


# Identities (design D6): how document suggestions, the profile's rows and remembered rejections are matched.
# Names and text compare by name_key. A row's identity comes from its current values, so a record's lines,
# sources and grounds change identity with the record's title.


def _ident(text: str | None) -> str:
    return name_key(text or "")


def identity_record(kind: str, title: str | None, organisation: str | None, start_date: str | None,
                    end_date: str | None) -> str:
    """A record, by its kind, title, organisation, start date and end date."""
    return f"record|{kind}|{_ident(title)}|{_ident(organisation)}|{start_date or ''}|{end_date or ''}"


def identity_line(record: str, text: str) -> str:
    """A description line, by its record's identity and its text."""
    return f"line|{record}|{_ident(text)}"


def identity_source(record: str, url: str | None = None, document_id: int | None = None) -> str:
    """A source, by its record's identity and its address (or uploaded document)."""
    return f"source|{record}|{f'document:{document_id}' if document_id is not None else _ident(url)}"


def identity_claim(skill_key: str) -> str:
    """A claim, by its skill's key; the caller resolves an alias to the skill it stands for first."""
    return f"claim|{skill_key}"


def identity_ground(claim: str, record: str) -> str:
    """A ground, by its claim's identity and its record's."""
    return f"ground|{claim}|{record}"


def identity_part_of(record: str, part_of: str) -> str:
    """A context link, by the dependent record's identity and the identity of the record it is part of."""
    return f"part_of|{record}|{part_of}"


def identity_highlight(text: str) -> str:
    """A highlight, by its text."""
    return f"highlight|{_ident(text)}"


def identity_cover(highlight: str, claim: str) -> str:
    """A highlight's coverage of a claim, by the highlight's identity and the claim's."""
    return f"cover|{highlight}|{claim}"


def identity_level(claim: str, level: str) -> str:
    """A level suggested for a claim, by the claim's identity and the level."""
    return f"level|{claim}|{level}"


def record_identity(row) -> str:
    """The identity of a record row (or anything with its fields as attributes)."""
    return identity_record(row.kind, row.title, row.organisation, row.start_date, row.end_date)


def _short(text: str) -> str:
    return text if len(text) <= LABEL_CHARS else text[:LABEL_CHARS - 3] + "..."


def record_label(row) -> str:
    """'title — organisation (dates)', for rejections and choices."""
    name = " — ".join(p for p in (row.title, row.organisation) if p) or f"(untitled {row.kind})"
    dates = "–".join(d for d in (row.start_date, row.end_date) if d)
    return _short(f"{name} ({dates})" if dates else name)


def ground_quote(row) -> str:
    """The quote of a ground the user adds without one: the record's title and organisation."""
    return ", ".join(p for p in (row.title, row.organisation) if p)


# Remembered rejections


def _remember(conn: Connection, identity: str, label: str, now: datetime) -> None:
    exists = conn.execute(select(profile_rejections.c.id).where(profile_rejections.c.identity == identity)).first()
    if exists is None:
        conn.execute(
            insert(profile_rejections).values(
                kind=identity.split("|", 1)[0], identity=identity, label=_short(label), created_at=now
            )
        )


def _forget(conn: Connection, identity: str) -> None:
    conn.execute(delete(profile_rejections).where(profile_rejections.c.identity == identity))


def forget_rejection(conn: Connection, rejection_id: int) -> None:
    """A suggestion with that identity may be offered again; nothing is recreated now."""
    conn.execute(delete(profile_rejections).where(profile_rejections.c.id == rejection_id))


# Lookups


def _get(conn: Connection, table: Table, row_id: int, what: str) -> Row:
    row = conn.execute(select(table).where(table.c.id == row_id)).first()
    if row is None:
        raise UserDataError(f"no such {what}")
    return row


def _record(conn: Connection, record_id: int) -> Row:
    return _get(conn, records, record_id, "record")


def _skill(conn: Connection, skill_id: int) -> Row:
    return _get(conn, skills, skill_id, "skill")


def _claim_of(conn: Connection, skill_id: int) -> Row | None:
    return conn.execute(select(claims).where(claims.c.skill_id == skill_id)).first()


def _resolved(conn: Connection, skill_id: int) -> Row:
    """The skill whose claim stands for this one: the skill it is an alias of, else itself."""
    from .queries import resolve_skill

    skill = _skill(conn, skill_id)
    return resolve_skill(conn, skill.key) or skill


def _claimed(conn: Connection, skill_id: int) -> tuple[Row, Row]:
    """(resolved skill, its claim), or UserDataError when the skill isn't in the profile."""
    skill = _resolved(conn, skill_id)
    claim = _claim_of(conn, skill.id)
    if claim is None:
        raise UserDataError(f"add {skill.name} to the profile first")
    return skill, claim


def _partial_date(value: str | None) -> str | None:
    """'2022' or '2022-09', or None for empty input."""
    value = (value or "").strip()
    if not value:
        return None
    if not _PARTIAL_DATE.fullmatch(value):
        raise UserDataError(f"{value!r} is not a year or year and month (use 2022 or 2022-09)")
    return value


def _next_position(conn: Connection, table: Table, *where) -> int:
    return conn.execute(select(func.coalesce(func.max(table.c.position), 0)).where(*where)).scalar_one() + 1


def _text(text: str | None, what: str) -> str:
    cleaned = collapse(text or "")
    if not cleaned:
        raise UserDataError(f"{what} needs text")
    return cleaned


# Records


def _record_values(fields: dict) -> dict:
    kind = fields.get("kind") or "other"
    if kind not in RECORD_KINDS:
        raise UserDataError(f"kind must be one of {', '.join(RECORD_KINDS)}")
    values = {
        "kind": kind,
        "title": _optional(collapse(fields.get("title") or "")),
        "organisation": _optional(collapse(fields.get("organisation") or "")),
        "location": _optional(fields.get("location")),
        "start_date": _partial_date(fields.get("start_date")),
        "end_date": _partial_date(fields.get("end_date")),
        "ongoing": bool(fields.get("ongoing")),
    }
    if not values["title"] and not values["organisation"]:
        raise UserDataError("a record needs a title or an organisation")
    return values


def _insert_record(conn: Connection, values: dict, origin: str, now: datetime, source_run_id: int | None = None,
                   disclosure: str = "public") -> int:
    return conn.execute(
        insert(records).values(
            disclosure=disclosure, origin=origin, source_run_id=source_run_id, created_at=now, updated_at=now, **values
        )
    ).inserted_primary_key[0]


def add_record(conn: Connection, fields: dict, now: datetime | None = None) -> int:
    """A record the user adds. `fields` holds kind, title, organisation, location, start_date, end_date, ongoing
    and optionally disclosure."""
    values, now = _record_values(fields), now or utcnow()
    disclosure = fields.get("disclosure") or "public"
    if disclosure not in DISCLOSURES:
        raise UserDataError(f"disclosure must be one of {', '.join(DISCLOSURES)}")
    record_id = _insert_record(conn, values, "user", now, disclosure=disclosure)
    _forget(
        conn, identity_record(**{f: values[f] for f in ("kind", "title", "organisation", "start_date", "end_date")})
    )
    return record_id


def update_record(conn: Connection, record_id: int, fields: dict, now: datetime | None = None) -> None:
    """Change a record's kind, title, organisation, location, dates or ongoing flag; the row becomes the user's.
    A change of identity remembers the old one."""
    before = _record(conn, record_id)
    values, now = _record_values(fields), now or utcnow()
    if all(getattr(before, f) == v for f, v in values.items()):
        return
    old = record_identity(before)
    if identity_record(**{f: values[f] for f in ("kind", "title", "organisation", "start_date", "end_date")}) != old:
        _remember(conn, old, f"{record_label(before)} (edited)", now)
    conn.execute(update(records).where(records.c.id == record_id).values(origin="user", updated_at=now, **values))


def delete_record(conn: Connection, record_id: int, now: datetime | None = None) -> None:
    """The record with its lines, sources and grounds; remembered. Records that were part of it lose the link and
    are flagged as having lost their context."""
    row, now = _record(conn, record_id), now or utcnow()
    _remember(conn, record_identity(row), record_label(row), now)
    conn.execute(
        update(records).where(records.c.part_of_id == record_id).values(part_of_id=None, context_lost_at=now)
    )
    conn.execute(delete(record_lines).where(record_lines.c.record_id == record_id))
    conn.execute(delete(record_sources).where(record_sources.c.record_id == record_id))
    grounds = conn.execute(delete(claim_records).where(claim_records.c.record_id == record_id)).rowcount
    conn.execute(delete(records).where(records.c.id == record_id))
    if grounds:
        skills_changed(conn)


def _chain(conn: Connection, record_id: int) -> list[int]:
    """The record and the records it is part of, directly or through others, nearest first."""
    out, current = [], record_id
    while current is not None and current not in out:
        out.append(current)
        current = conn.execute(select(records.c.part_of_id).where(records.c.id == current)).scalar()
    return out


def _link_part_of(conn: Connection, record: Row, part_of_id: int | None, now: datetime) -> None:
    """Point a record at the record it is part of (or none), refusing self and cycles; clears a lost-context flag."""
    if part_of_id is not None:
        parent = _record(conn, part_of_id)
        if part_of_id == record.id or record.id in _chain(conn, part_of_id):
            raise UserDataError(
                f"{record_label(record)} can't be part of {record_label(parent)}: it would be part of itself"
            )
    conn.execute(
        update(records).where(records.c.id == record.id).values(part_of_id=part_of_id, context_lost_at=None)
    )


def set_part_of(conn: Connection, record_id: int, part_of_id: int | None, now: datetime | None = None) -> None:
    """The user's choice of the record this one is part of (see "Record context"), or None for none. Replacing or
    clearing a link remembers the old one; the record becomes the user's."""
    row, now = _record(conn, record_id), now or utcnow()
    if row.part_of_id == part_of_id:
        if row.context_lost_at is not None:
            dismiss_lost_context(conn, record_id)
        return
    _link_part_of(conn, row, part_of_id, now)
    if row.part_of_id is not None:
        parent = _record(conn, row.part_of_id)
        _remember(conn, identity_part_of(record_identity(row), record_identity(parent)),
                  f"{record_label(row)} part of {record_label(parent)}", now)
    if part_of_id is not None:
        _forget(conn, identity_part_of(record_identity(row), record_identity(_record(conn, part_of_id))))
    conn.execute(update(records).where(records.c.id == record_id).values(origin="user", updated_at=now))


def dismiss_lost_context(conn: Connection, record_id: int) -> None:
    _record(conn, record_id)
    conn.execute(update(records).where(records.c.id == record_id).values(context_lost_at=None))


def set_disclosure(conn: Connection, record_id: int, disclosure: str, now: datetime | None = None) -> None:
    """'public' or 'private'. A private record still grounds claims; CVs must not show it (or what reveals it)."""
    if disclosure not in DISCLOSURES:
        raise UserDataError(f"disclosure must be one of {', '.join(DISCLOSURES)}")
    if _record(conn, record_id).disclosure != disclosure:
        conn.execute(
            update(records).where(records.c.id == record_id)
            .values(disclosure=disclosure, origin="user", updated_at=now or utcnow())
        )


# Description lines


def _line(conn: Connection, line_id: int) -> Row:
    return _get(conn, record_lines, line_id, "line")


def _insert_line(conn: Connection, record_id: int, text: str, origin: str, now: datetime) -> int:
    return conn.execute(
        insert(record_lines).values(
            record_id=record_id, text=text, origin=origin, created_at=now, updated_at=now,
            position=_next_position(conn, record_lines, record_lines.c.record_id == record_id),
        )
    ).inserted_primary_key[0]


def add_line(conn: Connection, record_id: int, text: str, now: datetime | None = None) -> int:
    """A description line at the end of the record."""
    record, text, now = _record(conn, record_id), _text(text, "a line"), now or utcnow()
    line_id = _insert_line(conn, record_id, text, "user", now)
    _forget(conn, identity_line(record_identity(record), text))
    return line_id


def update_line(conn: Connection, line_id: int, text: str, now: datetime | None = None) -> None:
    before, text, now = _line(conn, line_id), _text(text, "a line"), now or utcnow()
    if before.text == text:
        return
    record = record_identity(_record(conn, before.record_id))
    if identity_line(record, text) != identity_line(record, before.text):
        _remember(conn, identity_line(record, before.text), f"{before.text} (edited)", now)
    conn.execute(
        update(record_lines).where(record_lines.c.id == line_id).values(text=text, origin="user", updated_at=now)
    )


def delete_line(conn: Connection, line_id: int, now: datetime | None = None) -> None:
    row = _line(conn, line_id)
    _remember(conn, identity_line(record_identity(_record(conn, row.record_id)), row.text), row.text, now or utcnow())
    conn.execute(delete(record_lines).where(record_lines.c.id == line_id))


def move_line(conn: Connection, line_id: int, direction: str) -> None:
    """Swap a line with its neighbour in the record. Origin and updated_at stay."""
    if direction not in ("up", "down"):
        raise UserDataError("direction must be up or down")
    row = _line(conn, line_id)
    t = record_lines
    order = t.c.position.desc() if direction == "up" else t.c.position.asc()
    beyond = t.c.position < row.position if direction == "up" else t.c.position > row.position
    neighbour = conn.execute(
        select(t.c.id, t.c.position).where(t.c.record_id == row.record_id, beyond).order_by(order).limit(1)
    ).first()
    if neighbour is None:
        return
    conn.execute(update(t).where(t.c.id == row.id).values(position=neighbour.position))
    conn.execute(update(t).where(t.c.id == neighbour.id).values(position=row.position))


# Sources


def source_kind(url: str) -> str:
    """'repo' for GitHub and GitLab, 'doi' for doi.org and /doi/ addresses, else 'site'."""
    folded = url.casefold()
    if "github.com" in folded or "gitlab.com" in folded:
        return "repo"
    if "doi.org/" in folded or "/doi/" in folded:
        return "doi"
    return "site"


def _source_values(conn: Connection, url: str | None, document_id: int | None, kind: str | None) -> dict:
    url = _optional(url)
    if (url is None) == (document_id is None):
        raise UserDataError("a source is a web address or a document")
    if (
        document_id is not None
        and conn.execute(select(documents.c.id).where(documents.c.id == document_id)).first() is None
    ):
        raise UserDataError("no such document")
    kind = kind or ("document" if document_id is not None else source_kind(url))
    if kind not in SOURCE_KINDS:
        raise UserDataError(f"kind must be one of {', '.join(SOURCE_KINDS)}")
    return {"url": url, "document_id": document_id, "kind": kind}


def _insert_source(conn: Connection, record_id: int, values: dict, origin: str, now: datetime) -> int:
    return conn.execute(
        insert(record_sources).values(
            record_id=record_id, origin=origin, created_at=now,
            position=_next_position(conn, record_sources, record_sources.c.record_id == record_id), **values,
        )
    ).inserted_primary_key[0]


def add_source(conn: Connection, record_id: int, url: str | None = None, document_id: int | None = None,
               kind: str | None = None, now: datetime | None = None) -> int:
    """A web address (kind from the address unless given) or an uploaded document, at the end of the record's."""
    record, now = _record(conn, record_id), now or utcnow()
    values = _source_values(conn, url, document_id, kind)
    source_id = _insert_source(conn, record_id, values, "user", now)
    _forget(conn, identity_source(record_identity(record), values["url"], values["document_id"]))
    return source_id


def update_source(
    conn: Connection, source_id: int, url: str | None, kind: str | None, now: datetime | None = None
) -> None:
    """Change a web address source's address or kind; the row becomes the user's."""
    before = _get(conn, record_sources, source_id, "source")
    if before.document_id is not None:
        raise UserDataError("a document source can only be removed")
    values, now = _source_values(conn, url, None, kind), now or utcnow()
    if (values["url"], values["kind"]) == (before.url, before.kind):
        return
    record = record_identity(_record(conn, before.record_id))
    if identity_source(record, values["url"]) != identity_source(record, before.url):
        _remember(conn, identity_source(record, before.url), f"{before.url} (edited)", now)
    conn.execute(update(record_sources).where(record_sources.c.id == source_id).values(origin="user", **values))


def delete_source(conn: Connection, source_id: int, now: datetime | None = None) -> None:
    row = _get(conn, record_sources, source_id, "source")
    record = record_identity(_record(conn, row.record_id))
    _remember(conn, identity_source(record, row.url, row.document_id), row.url or f"document {row.document_id}",
              now or utcnow())
    conn.execute(delete(record_sources).where(record_sources.c.id == source_id))


# Claims and levels


def set_skill_level(conn: Connection, skill_id: int, level: str | None, now: datetime | None = None) -> None:
    """The user's own level for a skill: its claim's, so every posting marking it shows it. A skill that is an
    alias sets the claim of the skill it stands for. A level makes the claim (the skill joins the profile); None
    removes it (remove_profile_skill)."""
    if level is None:
        remove_profile_skill(conn, skill_id, now)
        return
    if level not in SKILL_LEVELS:
        raise UserDataError(f"level must be one of {', '.join(SKILL_LEVELS)}")
    skill, now = _resolved(conn, skill_id), now or utcnow()
    claim = _claim_of(conn, skill.id)
    if claim is None:
        conn.execute(
            insert(claims).values(
                skill_id=skill.id, level=level, level_origin="user", origin="user", created_at=now, updated_at=now
            )
        )
        _forget(conn, identity_claim(skill.key))
        skills_changed(conn)
    elif (claim.level, claim.level_origin) != (level, "user"):
        conn.execute(
            update(claims).where(claims.c.id == claim.id).values(level=level, level_origin="user", updated_at=now)
        )


def add_profile_skill(conn: Connection, name: str, level: str, now: datetime | None = None) -> int:
    """Add a skill (an existing one with the same key, or a new one) to the profile at a level the user chose;
    the id of the skill whose claim holds it (the alias's skill, for an alias)."""
    if level not in SKILL_LEVELS:
        raise UserDataError(f"level must be one of {', '.join(SKILL_LEVELS)}")
    now = now or utcnow()
    skill = get_or_create_skill(conn, name, now)
    set_skill_level(conn, skill.id, level, now)
    return _resolved(conn, skill.id).id


def _delete_claim(conn: Connection, claim_id: int) -> None:
    conn.execute(delete(claim_records).where(claim_records.c.claim_id == claim_id))
    conn.execute(delete(highlight_claims).where(highlight_claims.c.claim_id == claim_id))
    conn.execute(delete(claims).where(claims.c.id == claim_id))


def remove_profile_skill(conn: Connection, skill_id: int, now: datetime | None = None) -> None:
    """Delete the skill's claim with its grounds and the highlights' coverage of it; the highlights and the
    skill's marks on postings stay. Remembered, so document suggestions of it aren't offered."""
    skill = _resolved(conn, skill_id)
    claim = _claim_of(conn, skill.id)
    if claim is None:
        return
    _delete_claim(conn, claim.id)
    _remember(conn, identity_claim(skill.key), skill.name, now or utcnow())
    skills_changed(conn)


def rename_skill(conn: Connection, skill_id: int, name: str, now: datetime | None = None) -> None:
    """Change a skill's name, and so its identity, on every posting that marks it too. A claimed skill's old
    identity is remembered."""
    skill, now = _skill(conn, skill_id), now or utcnow()
    name = _clean_name(name)
    key = name_key(name)
    if conn.execute(select(skills.c.id).where(skills.c.key == key, skills.c.id != skill_id)).first() is not None:
        raise UserDataError(f"a skill named {name!r} already exists")
    alias = conn.execute(select(skill_aliases).where(skill_aliases.c.alias_key == key)).first()
    if alias is not None and alias.skill_id != skill_id:
        raise UserDataError(f"{name!r} is an alias of another skill; remove the alias first")
    claim = _claim_of(conn, skill_id)
    if claim is not None and key != skill.key:
        _remember(conn, identity_claim(skill.key), f"{skill.name} (renamed)", now)
    conn.execute(update(skills).where(skills.c.id == skill_id).values(name=name, key=key, updated_at=now))
    if claim is not None:
        skills_changed(conn)


# Grounds


def add_ground(conn: Connection, skill_id: int, record_id: int, quote: str | None = None,
               now: datetime | None = None) -> None:
    """Ground a profile skill's claim with a record. The quote defaults to the record's title and organisation."""
    skill, claim = _claimed(conn, skill_id)
    record, now = _record(conn, record_id), now or utcnow()
    exists = conn.execute(
        select(claim_records.c.claim_id).where(
            claim_records.c.claim_id == claim.id, claim_records.c.record_id == record_id
        )
    ).first()
    if exists is not None:
        raise UserDataError(f"{record_label(record)} already grounds {skill.name}")
    conn.execute(
        insert(claim_records).values(
            claim_id=claim.id, record_id=record_id, quote=collapse(quote or "") or ground_quote(record), origin="user",
            created_at=now,
        )
    )
    _forget(conn, identity_ground(identity_claim(skill.key), record_identity(record)))
    skills_changed(conn)  # an expansion context may have changed


def remove_ground(conn: Connection, skill_id: int, record_id: int, now: datetime | None = None) -> None:
    skill, claim = _claimed(conn, skill_id)
    record = _record(conn, record_id)
    removed = conn.execute(
        delete(claim_records).where(claim_records.c.claim_id == claim.id, claim_records.c.record_id == record_id)
    ).rowcount
    if removed:
        _remember(conn, identity_ground(identity_claim(skill.key), record_identity(record)),
                  f"{skill.name} on {record_label(record)}", now or utcnow())
        skills_changed(conn)


# Highlights and coverage


def _highlight(conn: Connection, highlight_id: int) -> Row:
    return _get(conn, highlights, highlight_id, "highlight")


def add_highlight(conn: Connection, text: str, now: datetime | None = None) -> int:
    text, now = _text(text, "a highlight"), now or utcnow()
    highlight_id = conn.execute(
        insert(highlights).values(text=text, origin="user", created_at=now, updated_at=now)
    ).inserted_primary_key[0]
    _forget(conn, identity_highlight(text))
    return highlight_id


def update_highlight(conn: Connection, highlight_id: int, text: str, now: datetime | None = None) -> None:
    before, text, now = _highlight(conn, highlight_id), _text(text, "a highlight"), now or utcnow()
    if before.text == text:
        return
    if identity_highlight(text) != identity_highlight(before.text):
        _remember(conn, identity_highlight(before.text), f"{before.text} (edited)", now)
    conn.execute(
        update(highlights).where(highlights.c.id == highlight_id).values(text=text, origin="user", updated_at=now)
    )


def delete_highlight(conn: Connection, highlight_id: int, now: datetime | None = None) -> None:
    """The highlight with its coverage; remembered. The claims it covered stay."""
    row = _highlight(conn, highlight_id)
    _remember(conn, identity_highlight(row.text), row.text, now or utcnow())
    covered = conn.execute(delete(highlight_claims).where(highlight_claims.c.highlight_id == highlight_id)).rowcount
    conn.execute(delete(highlights).where(highlights.c.id == highlight_id))
    if covered:
        skills_changed(conn)


def add_coverage(conn: Connection, highlight_id: int, skill_id: int, quote: str | None = None,
                 now: datetime | None = None) -> None:
    """The highlight covers a profile skill's claim; the quote, if given, names the skill in the highlight."""
    highlight, now = _highlight(conn, highlight_id), now or utcnow()
    skill, claim = _claimed(conn, skill_id)
    exists = conn.execute(
        select(highlight_claims.c.claim_id)
        .where(highlight_claims.c.highlight_id == highlight_id, highlight_claims.c.claim_id == claim.id)
    ).first()
    if exists is not None:
        raise UserDataError(f"the highlight already covers {skill.name}")
    conn.execute(
        insert(highlight_claims).values(
            highlight_id=highlight_id, claim_id=claim.id, quote=_optional(collapse(quote or "")), origin="user",
            created_at=now,
        )
    )
    _forget(conn, identity_cover(identity_highlight(highlight.text), identity_claim(skill.key)))
    skills_changed(conn)  # an expansion context may have changed


def remove_coverage(conn: Connection, highlight_id: int, skill_id: int, now: datetime | None = None) -> None:
    highlight = _highlight(conn, highlight_id)
    skill, claim = _claimed(conn, skill_id)
    removed = conn.execute(
        delete(highlight_claims)
        .where(highlight_claims.c.highlight_id == highlight_id, highlight_claims.c.claim_id == claim.id)
    ).rowcount
    if removed:
        _remember(conn, identity_cover(identity_highlight(highlight.text), identity_claim(skill.key)),
                  f"{skill.name} in “{highlight.text}”", now or utcnow())
        skills_changed(conn)


# Aliases


def merge_skill(conn: Connection, merged_id: int, kept_id: int, now: datetime | None = None) -> None:
    """Merge a skill into a profile skill: the merged skill's grounds and coverage move to the kept skill's claim
    (one per record or highlight), its claim is removed, and its key becomes an alias of the kept skill, as do the
    aliases that pointed at it. Link overrides naming it name the kept skill. The kept claim's level, and posting
    marks, rejected posting suggestions and the eval's matching, are unchanged."""
    merged, kept, now = _skill(conn, merged_id), _skill(conn, kept_id), now or utcnow()
    if merged.id == kept.id:
        raise UserDataError("a skill can't be merged into itself")
    kept_claim = _claim_of(conn, kept.id)
    if kept_claim is None:
        raise UserDataError(f"add {kept.name} to the profile before merging into it")
    merged_claim = _claim_of(conn, merged.id)
    if merged_claim is not None:
        for table, target in ((claim_records, "record_id"), (highlight_claims, "highlight_id")):
            have = set(conn.execute(select(table.c[target]).where(table.c.claim_id == kept_claim.id)).scalars())
            moved = [
                {**row._mapping, "claim_id": kept_claim.id}
                for row in conn.execute(select(table).where(table.c.claim_id == merged_claim.id))
                if getattr(row, target) not in have
            ]
            if moved:
                conn.execute(insert(table), moved)
        _delete_claim(conn, merged_claim.id)
    conn.execute(update(skill_aliases).where(skill_aliases.c.skill_id == merged.id).values(skill_id=kept.id))
    conn.execute(delete(skill_aliases).where(skill_aliases.c.alias_key.in_([merged.key, kept.key])))
    conn.execute(insert(skill_aliases).values(alias_key=merged.key, skill_id=kept.id, created_at=now))
    conn.execute(
        update(skill_link_overrides).where(skill_link_overrides.c.skill_id == merged.id).values(skill_id=kept.id)
    )
    _forget(conn, identity_claim(merged.key))
    skills_changed(conn)


def remove_alias(conn: Connection, alias_key: str) -> None:
    """The alias goes; the merged skill's claim isn't recreated."""
    if conn.execute(delete(skill_aliases).where(skill_aliases.c.alias_key == alias_key)).rowcount:
        skills_changed(conn)


# Profile details


def _detail_values(kind: str, text: str, label: str | None) -> dict:
    if kind not in DETAIL_KINDS:
        raise UserDataError(f"kind must be one of {', '.join(DETAIL_KINDS)}")
    return {"kind": kind, "text": _text(text, "a detail"), "label": _optional(label)}


def add_detail(conn: Connection, kind: str, text: str, label: str | None = None, now: datetime | None = None) -> int:
    """A name, headline, contact detail, summary or goal statement."""
    now = now or utcnow()
    return conn.execute(
        insert(profile_details).values(created_at=now, updated_at=now, **_detail_values(kind, text, label))
    ).inserted_primary_key[0]


def update_detail(conn: Connection, detail_id: int, kind: str, text: str, label: str | None = None,
                  now: datetime | None = None) -> None:
    _get(conn, profile_details, detail_id, "detail")
    conn.execute(
        update(profile_details).where(profile_details.c.id == detail_id)
        .values(updated_at=now or utcnow(), **_detail_values(kind, text, label))
    )


def delete_detail(conn: Connection, detail_id: int) -> None:
    conn.execute(delete(profile_details).where(profile_details.c.id == detail_id))


# Document suggestions (derived rows are read through queries.profile_suggestions, never written here)


def _offer(conn: Connection, suggestion_id: int) -> tuple[str, dict]:
    """(kind, offer) holding the suggestion as it is offered now, or UserDataError."""
    from .queries import SUGGESTION_KINDS, profile_suggestions

    offered = profile_suggestions(conn)
    for kind in SUGGESTION_KINDS:
        for offer in offered[kind]:
            if suggestion_id in offer["ids"]:
                return kind, offer
    raise UserDataError("that suggestion is no longer offered")


def _accept_offer(conn: Connection, kind: str, offer: dict, now: datetime) -> None:
    """Copy what an offer offers into the profile, with origin 'suggestion' (and level_origin 'model')."""
    run_id = offer["run_id"]
    if kind == "record":
        record_id = offer["existing_id"]
        if record_id is None:
            record_id = _insert_record(conn, offer["record"], "suggestion", now, source_run_id=run_id)
        for line in offer["lines"]:
            _insert_line(conn, record_id, collapse(line["text"]), "suggestion", now)
        for source in offer["sources"]:
            _insert_source(conn, record_id, {"url": source["url"], "document_id": None, "kind": source["kind"]},
                           "suggestion", now)
    elif kind == "claim":
        claim_id = offer["claim_id"]
        if claim_id is None:
            skill = conn.execute(select(skills).where(skills.c.key == offer["skill_key"])).first()
            skill = skill or get_or_create_skill(conn, offer["suggested_name"], now)
            claim_id = conn.execute(
                insert(claims).values(
                    skill_id=skill.id, level=offer["level"], level_origin="model", origin="suggestion",
                    source_run_id=run_id, created_at=now, updated_at=now,
                )
            ).inserted_primary_key[0]
        elif offer["level"] is not None:
            conn.execute(
                update(claims).where(claims.c.id == claim_id)
                .values(level=offer["level"], level_origin="model", updated_at=now)
            )
        for ground in offer["grounds"]:
            conn.execute(insert(claim_records).values(
                claim_id=claim_id, record_id=ground["record_id"], quote=collapse(ground["quote"]), origin="suggestion",
                created_at=now,
            ))
        skills_changed(conn)
    elif kind == "part_of":
        record = _record(conn, offer["record_id"])
        if record.part_of_id is not None:
            raise UserDataError(f"{record_label(record)} is already part of another record")
        _link_part_of(conn, record, offer["part_of_id"], now)
    else:
        highlight_id = offer["existing_id"]
        if highlight_id is None:
            highlight_id = conn.execute(
                insert(highlights).values(
                    text=collapse(offer["text"]), origin="suggestion", source_run_id=run_id, created_at=now,
                    updated_at=now,
                )
            ).inserted_primary_key[0]
        for cover in offer["covers"]:
            conn.execute(insert(highlight_claims).values(
                highlight_id=highlight_id, claim_id=cover["claim_id"], quote=_optional(cover["quote"]),
                origin="suggestion", created_at=now,
            ))
        if offer["covers"]:
            skills_changed(conn)


def accept_profile_suggestion(conn: Connection, suggestion_id: int, now: datetime | None = None) -> str:
    """Copy what a suggestion offers now into the profile: a new row with what it holds, or the additions offered
    for an existing one. Rows and levels the user changed are never touched (they aren't offered). The kind."""
    kind, offer = _offer(conn, suggestion_id)
    _accept_offer(conn, kind, offer, now or utcnow())
    return kind


def _offered_identities(kind: str, offer: dict) -> list[tuple[str, str]]:
    """(identity, label) of everything an offer offers: itself when new, else each addition."""
    if offer["status"] == "new":
        label = {"record": offer.get("label"), "claim": offer.get("name"), "highlight": offer.get("text")}.get(kind)
        if kind == "part_of":
            label = f"{offer['record_label']} part of {offer['part_of_label']}"
        return [(offer["identity"], label)]
    if kind == "record":
        return [(x["identity"], f"{x['text']} (line of {offer['label']})") for x in offer["lines"]] + [
            (x["identity"], f"{x['url']} (source of {offer['label']})") for x in offer["sources"]
        ]
    if kind == "claim":
        out = [(g["identity"], f"{offer['name']} on {g['label']}") for g in offer["grounds"]]
        if offer["level"]:
            out.append((identity_level(offer["identity"], offer["level"]), f"{offer['name']} at {offer['level']}"))
        return out
    return [(c["identity"], f"{c['name']} in “{offer['text']}”") for c in offer["covers"]]


def reject_profile_suggestion(conn: Connection, suggestion_id: int, now: datetime | None = None) -> None:
    """Remember what a suggestion offers now as rejected, so no run offers it again."""
    kind, offer = _offer(conn, suggestion_id)
    now = now or utcnow()
    for identity, label in _offered_identities(kind, offer):
        _remember(conn, identity, label, now)


def accept_all_profile_suggestions(conn: Connection, kind: str, now: datetime | None = None) -> int:
    """Accept every suggestion of one kind offered now, from every document; the number accepted. What this makes
    available (grounds waiting for a record, say) is offered afterwards, not accepted here. A context link refused
    for making a cycle is skipped."""
    from .queries import SUGGESTION_KINDS, profile_suggestions

    if kind not in SUGGESTION_KINDS:
        raise UserDataError(f"kind must be one of {', '.join(SUGGESTION_KINDS)}")
    now, accepted = now or utcnow(), 0
    for offer in profile_suggestions(conn)[kind]:
        try:
            _accept_offer(conn, kind, offer, now)
        except UserDataError:
            if kind != "part_of":
                raise
            continue
        accepted += 1
    return accepted


# Resetting


def reset_knowledge_base(conn: Connection) -> dict[str, int]:
    """Delete every record, claim and highlight, with their lines, sources, grounds and coverage, without
    remembering them; details, aliases, rejections, link overrides, posting data and documents stay. The number
    of records, claims and highlights deleted."""
    counts = {
        "records": conn.execute(select(func.count()).select_from(records)).scalar_one(),
        "claims": conn.execute(select(func.count()).select_from(claims)).scalar_one(),
        "highlights": conn.execute(select(func.count()).select_from(highlights)).scalar_one(),
    }
    for table in (claim_records, highlight_claims, record_lines, record_sources):
        conn.execute(delete(table))
    conn.execute(update(records).values(part_of_id=None))
    for table in (records, claims, highlights):
        conn.execute(delete(table))
    return counts


# --- Link overrides ---


def set_link_override(
    conn: Connection, posting_skill: str, skill_id: int | None, relation: str | None = None, now: datetime | None = None
) -> None:
    """The user's link for a posting skill (by name or key): a profile skill and a relation, or skill_id None for
    "no link". It takes precedence over every other source and is never judged again."""
    key = name_key(_clean_name(posting_skill))
    if skill_id is None:
        relation = None
    else:
        if _claim_of(conn, _skill(conn, skill_id).id) is None:
            raise UserDataError("link to a skill in the profile")
        if relation not in LINK_RELATIONS:
            raise UserDataError(f"relation must be one of {', '.join(LINK_RELATIONS)}")
    values = {"skill_id": skill_id, "relation": relation, "created_at": now or utcnow()}
    if conn.execute(
        select(skill_link_overrides.c.posting_key).where(skill_link_overrides.c.posting_key == key)
    ).first():
        conn.execute(update(skill_link_overrides).where(skill_link_overrides.c.posting_key == key).values(**values))
    else:
        conn.execute(insert(skill_link_overrides).values(posting_key=key, **values))


def clear_link_override(conn: Connection, posting_skill: str) -> None:
    """Back to the model's link; the skill is judged if it never was."""
    removed = conn.execute(
        delete(skill_link_overrides).where(skill_link_overrides.c.posting_key == name_key(posting_skill))
    ).rowcount
    if removed:
        skills_changed(conn)


# --- Tailored CVs: frozen copies of what tailor.py proposed ---


def save_tailored_cv(conn: Connection, job_id: int, proposal, now: datetime | None = None) -> int:
    """Store a proposal (tailor.Proposal) as a CV for the posting: its items in print order, each with the content
    copied now, the match score, the ranking method and the choice it came from. The id of the new CV."""
    from .cvdoc.model import CONTENT_VERSION, content_to_json

    now = now or utcnow()
    choice = {"choice": proposal.choice.to_json(), "left_out": proposal.content["left_out"]}
    cv_id = conn.execute(
        insert(tailored_cvs).values(
            job_id=job_id, method=proposal.method, content_version=CONTENT_VERSION, match_score=proposal.score,
            choice_json=json.dumps(choice), created_at=now, updated_at=now,
        )
    ).inserted_primary_key[0]
    positions: dict[str, int] = {}
    for item in proposal.content["items"]:
        positions[item["section"]] = positions.get(item["section"], 0) + 1
        conn.execute(
            insert(tailored_cv_items).values(
                cv_id=cv_id, section=item["section"], position=positions[item["section"]],
                source_kind=item["source_kind"], source_id=item["source_id"],
                payload_json=content_to_json(item["payload"]), created_at=now,
            )
        )
    return cv_id


def _cv_item(conn: Connection, cv_id: int, item_id: int) -> Row:
    row = conn.execute(
        select(tailored_cv_items).where(tailored_cv_items.c.id == item_id, tailored_cv_items.c.cv_id == cv_id)
    ).first()
    if row is None:
        raise UserDataError("no such item on this CV")
    return row


def _touch_cv(conn: Connection, cv_id: int, now: datetime, **values) -> None:
    conn.execute(update(tailored_cvs).where(tailored_cvs.c.id == cv_id).values(updated_at=now, **values))


def move_cv_item(conn: Connection, cv_id: int, item_id: int, direction: str, now: datetime | None = None) -> None:
    """Swap an item with its neighbour in the same section of the CV; nothing at either end."""
    if direction not in ("up", "down"):
        raise UserDataError("direction must be up or down")
    row, t = _cv_item(conn, cv_id, item_id), tailored_cv_items
    order = t.c.position.desc() if direction == "up" else t.c.position.asc()
    beyond = t.c.position < row.position if direction == "up" else t.c.position > row.position
    neighbour = conn.execute(
        select(t.c.id, t.c.position)
        .where(t.c.cv_id == cv_id, t.c.section == row.section, beyond)
        .order_by(order)
        .limit(1)
    ).first()
    if neighbour is None:
        return
    conn.execute(update(t).where(t.c.id == row.id).values(position=neighbour.position))
    conn.execute(update(t).where(t.c.id == neighbour.id).values(position=row.position))
    _touch_cv(conn, cv_id, now or utcnow())


def _payload_kinds(payload: dict) -> set[str]:
    return {payload["kind"]} | {k for child in payload.get("children", ()) for k in _payload_kinds(child)}


def remove_cv_item(conn: Connection, cv_id: int, item_id: int, now: datetime | None = None) -> None:
    """Remove an item from the CV; records printed under it go with it, and their kinds now count as left out
    (so "Selected Publications" heads what remains)."""
    from .cvdoc.model import content_from_json

    row = _cv_item(conn, cv_id, item_id)
    conn.execute(delete(tailored_cv_items).where(tailored_cv_items.c.id == item_id))
    values = {}
    if row.source_kind in ("record", "course_group"):
        cv = conn.execute(select(tailored_cvs).where(tailored_cvs.c.id == cv_id)).one()
        choice = json.loads(cv.choice_json)
        kinds = _payload_kinds(content_from_json(row.payload_json, cv.content_version))
        choice["left_out"] = sorted(set(choice.get("left_out", [])) | kinds, key=RECORD_KINDS.index)
        values["choice_json"] = json.dumps(choice)
    _touch_cv(conn, cv_id, now or utcnow(), **values)


def delete_tailored_cv(conn: Connection, cv_id: int) -> None:
    """The CV and its items; other CVs and the profile stay."""
    conn.execute(delete(tailored_cv_items).where(tailored_cv_items.c.cv_id == cv_id))
    if not conn.execute(delete(tailored_cvs).where(tailored_cvs.c.id == cv_id)).rowcount:
        raise UserDataError("no such CV")
