"""Builds the demo database through the app's own writers: postings through the public import, user data through
userdata (and documents), model output through the job queue with the scripted client, and a saved tailored CV."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Connection, Engine

from .. import documents, tailor, userdata
from ..db import (
    applications,
    claims,
    dismiss_reasons,
    enrichment_skills,
    highlights,
    llm_jobs,
    posting_enrichments,
    postings,
    profile_details,
    records,
)
from ..db import documents as document_rows
from ..enrich import jobs
from ..importer import import_files
from ..parsers.posting_file import PARSER
from . import persona
from .scripted import CHAT_MODEL, EMBED_MODEL, ScriptedClient

POSTINGS_DIR = Path(__file__).parent / "postings"
DEFAULT_DB_URL = "sqlite:///demo/jobhunt.db"
DEFAULT_DOCUMENTS_DIR = "demo/documents"


class DemoError(Exception):
    """The demo can't be built here; nothing was changed."""


@dataclass
class Built:
    postings: int
    snapshots: int
    runs: int
    links_jobs: int
    cv_id: int


def posting_files() -> list[Path]:
    """The demo's posting files in import order: first captures by posting ID, then the recapture."""
    files = sorted(POSTINGS_DIR.glob("*.json"))
    return [f for f in files if "-" not in f.stem] + [f for f in files if "-" in f.stem]


def refusal(engine: Engine, documents_dir: Path) -> str | None:
    """Why the demo must not be built into this database and folder, or None. Reads only, so a real database
    is never upgraded or changed by asking."""
    if documents_dir.exists() and any(documents_dir.iterdir()):
        return f"the documents folder {documents_dir} isn't empty"
    tables = set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        for table in (postings, records, claims, highlights, profile_details, document_rows):
            if table.name in tables and conn.execute(select(func.count()).select_from(table)).scalar_one():
                return f"the database isn't empty (it has {table.name})"
    return None


def build(engine: Engine, documents_dir: Path) -> Built:
    """Fill an empty, migrated database with the demo. Deterministic: the same rows every time."""
    now = persona.DEMO_DATE
    client = ScriptedClient()
    with engine.begin() as conn:
        userdata.set_setting(conn, "llm.model", CHAT_MODEL, now)
        userdata.set_setting(conn, "llm.embed_model", EMBED_MODEL, now)
        skill_ids = _profile(conn, now)

    results = []
    for path in posting_files():
        results += import_files(engine, [path], parsers=[PARSER], now=now)
    refused = [r for r in results if r.outcome == "rejected"]
    if refused:
        raise DemoError(f"a demo posting was rejected: {refused[0].name}: {refused[0].reason}")
    job_ids = {r.external_id: r.job_id for r in results}

    with engine.begin() as conn:
        for job_id in job_ids.values():
            jobs.enqueue(conn, job_id, now=now)
    _drain(engine, client)

    with engine.begin() as conn:
        _triage(conn, job_ids, now)
        _suggestions(conn, job_ids, now)
        for name, link in persona.LINK_OVERRIDES.items():
            skill_id, relation = (skill_ids[link[0]], link[1]) if link else (None, None)
            userdata.set_link_override(conn, name, skill_id, relation, now)
        _applications(conn, job_ids, documents_dir, now)
    _drain(engine, client)

    with engine.begin() as conn:
        job_id = job_ids[persona.TAILORED_FOR]
        cv_id = userdata.save_tailored_cv(conn, job_id, tailor.propose(conn, job_id, tailor.Choice(), now), now)
        userdata.set_setting(conn, "demo.created_at", now, now)
        return Built(
            postings=len(job_ids),
            snapshots=sum(r.outcome in ("new", "updated") for r in results),
            runs=conn.execute(select(func.count()).select_from(posting_enrichments)).scalar_one(),
            links_jobs=conn.execute(select(func.count()).where(llm_jobs.c.kind == "links")).scalar_one(),
            cv_id=cv_id,
        )


def _drain(engine: Engine, client: ScriptedClient) -> None:
    """Run every queued job; a failed one is a bug in the demo."""
    while (status := jobs.run_next(engine, client)) is not None:
        if status != "done":
            with engine.connect() as conn:
                job = conn.execute(select(llm_jobs).order_by(llm_jobs.c.id.desc()).limit(1)).one()
            raise DemoError(f"a demo {job.kind} job ended {status}: {job.error}")


def _profile(conn: Connection, now) -> dict[str, int]:
    """Details, records, claims with grounds, aliases and highlights; profile skill name -> skill id."""
    for kind, text, label in persona.DETAILS:
        userdata.add_detail(conn, kind, text, label, now)
    record_ids = {}
    for key, spec in persona.RECORDS.items():
        record_ids[key] = userdata.add_record(conn, spec, now)
        for line in spec.get("lines", ()):
            userdata.add_line(conn, record_ids[key], line, now)
        for url in spec.get("sources", ()):
            userdata.add_source(conn, record_ids[key], url, now=now)
    for key, spec in persona.RECORDS.items():
        if "part_of" in spec:
            userdata.set_part_of(conn, record_ids[key], record_ids[spec["part_of"]], now)
    skill_ids = {}
    for name, (level, grounds) in persona.CLAIMS.items():
        skill_ids[name] = userdata.add_profile_skill(conn, name, level, now)
        for record, quote in grounds:
            userdata.add_ground(conn, skill_ids[name], record_ids[record], quote, now)
    for merged, kept in persona.ALIASES.items():
        userdata.merge_skill(conn, userdata.get_or_create_skill(conn, merged, now).id, skill_ids[kept], now)
    for text, covered in persona.HIGHLIGHTS.items():
        highlight_id = userdata.add_highlight(conn, text, now)
        for name in covered:
            userdata.add_coverage(conn, highlight_id, skill_ids[name], None, now)
    return skill_ids


def _triage(conn: Connection, job_ids: dict[str, int], now) -> None:
    for external_id, notes in persona.TRIAGE.items():
        job_id = job_ids[external_id]
        for field in userdata.RATING_FIELDS:
            userdata.set_rating(conn, job_id, field, notes[field], now)
        for tag in notes.get("tags", ()):
            userdata.add_tag(conn, job_id, tag, now)
        if "notes" in notes:
            userdata.set_notes(conn, job_id, notes["notes"], now)
    for external_id, (reason, comment) in persona.DISMISSED.items():
        reason_id = conn.execute(select(dismiss_reasons.c.id).where(dismiss_reasons.c.key == reason)).scalar_one()
        userdata.dismiss(conn, job_ids[external_id], [reason_id], comment, now)


def _suggestions(conn: Connection, job_ids: dict[str, int], now) -> None:
    """Marks by hand, and accepted and rejected suggestions of each posting's latest run."""
    for external_id, marks in persona.MARKS.items():
        for name, quote, importance in marks:
            userdata.add_skill_mark(conn, job_ids[external_id], name, quote, now, importance)
    for external_id, names in persona.ACCEPTED.items():
        latest = (
            select(func.max(posting_enrichments.c.id))
            .where(posting_enrichments.c.job_id == job_ids[external_id])
            .scalar_subquery()
        )
        for name in names:
            item_id = conn.execute(
                select(enrichment_skills.c.id).where(
                    enrichment_skills.c.enrichment_id == latest, enrichment_skills.c.name == name,
                    enrichment_skills.c.verified.is_(True),
                ).order_by(enrichment_skills.c.position).limit(1)
            ).scalar_one()
            userdata.accept_suggestion(conn, item_id, now)
    for external_id, rejected in persona.REJECTED.items():
        for name, reason in rejected:
            userdata.reject_suggestion(conn, job_ids[external_id], name, reason, now)


def _applications(conn: Connection, job_ids: dict[str, int], documents_dir: Path, now) -> None:
    app_ids = {}
    for external_id, spec in persona.APPLICATIONS.items():
        app_id = app_ids[external_id] = userdata.start_application(conn, job_ids[external_id], now)
        for kind, day, note in spec["events"]:
            userdata.add_event(conn, app_id, kind, day, note, now)
        if "next_action" in spec:
            userdata.set_next_action(conn, app_id, *spec["next_action"], now)
        if "compensation" in spec:
            row = conn.execute(select(applications).where(applications.c.id == app_id)).one()
            userdata.update_application(conn, app_id, row.title, row.company, row.url, spec["compensation"], now)

    company = userdata.get_or_create_company(conn, persona.COMPANY["name"], now)
    userdata.update_company(conn, company.id, now=now, **persona.COMPANY)
    first = app_ids[persona.TAILORED_FOR]
    contact_id = userdata.save_contact(conn, None, company_id=company.id, now=now, **persona.CONTACT)
    userdata.link_contact(conn, first, contact_id)

    filename, label, text = persona.COVER_LETTER
    stored = documents.store_upload(documents_dir, text.encode("utf-8"), filename)
    document_id = userdata.add_document(conn, stored, label, "cover_letter", now)
    userdata.link_document(conn, first, document_id)
