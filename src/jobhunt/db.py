"""Database tables and engine setup, portable across Postgres and SQLite (SQLAlchemy Core)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    make_url,
)
from sqlalchemy.engine import Engine
from sqlalchemy.types import TypeDecorator

DEFAULT_DB_URL = "sqlite:///data/jobhunt.db"


class UTCDateTime(TypeDecorator):
    """Aware UTC datetimes in Python, stored as naive UTC so both databases behave the same."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


metadata = MetaData()

# --- Captured data, written only by store.py. ---
# A posting's key is assigned by the database; the accepting parser's source and external ID identify it.
postings = Table(
    "postings",
    metadata,
    Column("job_id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(100), nullable=False),  # e.g. a website's host without "www."
    Column("external_id", String(200), nullable=False),  # the source's own ID, kept opaque
    Column("url", Text, nullable=False),
    Column("first_seen_at", UTCDateTime, nullable=False),
    Column("last_seen_at", UTCDateTime, nullable=False),
    UniqueConstraint("source", "external_id", name="uq_postings_source_external_id"),
)

captures = Table(
    "captures",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sha256", String(64), nullable=False, unique=True),  # of the raw file bytes
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False, index=True),
    Column("source_name", Text, nullable=False),
    Column("captured_at", UTCDateTime, nullable=False),  # reported by the parser, else the file's mtime
    Column("imported_at", UTCDateTime, nullable=False),
    Column("raw_gz", LargeBinary, nullable=False),  # the original file, gzipped
    Column("parser", Text),  # "name@version" of the parser that accepted it; NULL before parsers were plug-ins
)

# details_json and volatile_json are JSON objects in store.canonical_details form, as text for portability.
posting_snapshots = Table(
    "posting_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False, index=True),
    Column("capture_id", Integer, ForeignKey("captures.id"), nullable=False),
    Column("parser", Text, nullable=False),  # "name@version"; "1" for snapshots stored before parsers were plug-ins
    Column("fingerprint", String(64), nullable=False),  # of the compared content (store.fingerprint)
    Column("title", Text, nullable=False),
    Column("company", Text, nullable=False),
    Column("location", Text),
    Column("workplace_type", Text),
    Column("employment_type", Text),
    Column("posted_on_estimate", Date),
    Column("posted_on_precision", Text),
    Column("description_html", Text, nullable=False),
    Column("description_text", Text, nullable=False),
    Column("details_json", Text, nullable=False),  # compared between captures
    Column("volatile_json", Text, nullable=False),  # stored, not compared
)


# --- User-authored data, written only by userdata.py. Imports never touch these tables. ---

posting_triage = Table(
    "posting_triage",
    metadata,
    Column("job_id", Integer, ForeignKey("postings.job_id"), primary_key=True),
    Column("interest", SmallInteger),  # 1-5, NULL until the user sets it
    Column("fit", SmallInteger),
    Column("notes", Text),  # markdown
    Column("updated_at", UTCDateTime, nullable=False),
    Column("skills_complete_at", UTCDateTime),  # set when the user has marked every skill the posting asks for
    Column("skills_first_complete_at", UTCDateTime),  # the first time the flag was set; never cleared
)

tags = Table(
    "tags",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("key", Text, nullable=False, unique=True),  # userdata.name_key(name)
)

posting_tags = Table(
    "posting_tags",
    metadata,
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False),
    Column("tag_id", Integer, ForeignKey("tags.id"), nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    PrimaryKeyConstraint("job_id", "tag_id"),
)

dismiss_reasons = Table(
    "dismiss_reasons",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("label", Text, nullable=False),
    Column("key", Text, nullable=False, unique=True),
    Column("position", Integer, nullable=False),
)

# A posting is dismissed while it has a row with restored_at NULL; restoring keeps the row.
posting_dismissals = Table(
    "posting_dismissals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False, index=True),
    Column("dismissed_at", UTCDateTime, nullable=False),
    Column("comment", Text),
    Column("restored_at", UTCDateTime),
)

posting_dismissal_reasons = Table(
    "posting_dismissal_reasons",
    metadata,
    Column("dismissal_id", Integer, ForeignKey("posting_dismissals.id"), nullable=False),
    Column("reason_id", Integer, ForeignKey("dismiss_reasons.id"), nullable=False),
    PrimaryKeyConstraint("dismissal_id", "reason_id"),
)

skills = Table(
    "skills",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("key", Text, nullable=False, unique=True),
    Column("updated_at", UTCDateTime, nullable=False),
)

posting_skill_marks = Table(
    "posting_skill_marks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False, index=True),
    Column("skill_id", Integer, ForeignKey("skills.id"), nullable=False, index=True),
    Column("quote", Text, nullable=False),  # whitespace collapsed
    Column("snapshot_id", Integer, ForeignKey("posting_snapshots.id"), nullable=False),  # the text it was marked on
    Column("created_at", UTCDateTime, nullable=False),
    Column("importance", Text),  # 'required', 'preferred' or NULL (unspecified)
    Column("origin", Text, nullable=False, server_default="selection"),  # 'selection' or 'suggestion'
)

# A skill the user rejected as a model suggestion for this posting, in every run until undone.
rejected_suggestions = Table(
    "rejected_suggestions",
    metadata,
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False),
    Column("skill_key", Text, nullable=False),  # userdata.name_key(skill name)
    Column("created_at", UTCDateTime, nullable=False),
    Column("reason", Text),  # 'not-a-skill', 'not-for-me' or NULL (rejected before reasons existed)
    PrimaryKeyConstraint("job_id", "skill_key"),
)

# Keys: llm.model, llm.num_ctx, llm.segmenter, llm.embed_model, eval.holdout_start, demo.created_at; defaults and
# validation live in userdata.py.
app_settings = Table(
    "app_settings",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

companies = Table(
    "companies",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("key", Text, nullable=False, unique=True),  # matched to posting/application company names
    Column("website_url", Text),
    Column("careers_url", Text),
    Column("notes", Text),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

contacts = Table(
    "contacts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("company_id", Integer, ForeignKey("companies.id"), index=True),
    Column("role", Text),
    Column("profile_url", Text),
    Column("notes", Text),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

contact_emails = Table(
    "contact_emails",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("contact_id", Integer, ForeignKey("contacts.id"), nullable=False, index=True),
    Column("email", Text, nullable=False),
)

# job_id is NULL for applications entered by hand; NULLs never clash in the unique constraint.
applications = Table(
    "applications",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, ForeignKey("postings.job_id"), unique=True),
    Column("title", Text, nullable=False),
    Column("company", Text, nullable=False),
    Column("url", Text),
    Column("status", Text, nullable=False),  # cached; only userdata.recompute_status writes it
    Column("status_date", Date),
    Column("next_action", Text),
    Column("next_action_due", Date),
    Column("compensation_notes", Text),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

application_events = Table(
    "application_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("application_id", Integer, ForeignKey("applications.id"), nullable=False, index=True),
    Column("kind", Text, nullable=False),
    Column("event_date", Date, nullable=False),
    Column("note", Text),
    Column("created_at", UTCDateTime, nullable=False),
)

# File bytes live in the documents folder at <sha256[:2]>/<sha256>; see documents.py.
documents = Table(
    "documents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sha256", String(64), nullable=False, index=True),
    Column("label", Text, nullable=False),
    Column("kind", Text, nullable=False),  # 'cv', 'cover_letter' or 'other'
    Column("original_filename", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("uploaded_at", UTCDateTime, nullable=False),
    Column("text_content", Text),
    Column("text_status", Text, nullable=False),  # 'extracted', 'unsupported' or 'failed: ...'
)

application_documents = Table(
    "application_documents",
    metadata,
    Column("application_id", Integer, ForeignKey("applications.id"), nullable=False),
    Column("document_id", Integer, ForeignKey("documents.id"), nullable=False),
    PrimaryKeyConstraint("application_id", "document_id"),
)

application_contacts = Table(
    "application_contacts",
    metadata,
    Column("application_id", Integer, ForeignKey("applications.id"), nullable=False),
    Column("contact_id", Integer, ForeignKey("contacts.id"), nullable=False),
    PrimaryKeyConstraint("application_id", "contact_id"),
)

# The profile, a knowledge base CVs are built from: records (facts), claims (one per skill, with the level),
# grounds (a claim's records), highlights (CV wording, covering claims), aliases, details and rejections.
# `origin` is 'user' (made or last changed by the user), 'suggestion' (copied from an accepted document
# suggestion) or 'model' (from an automatic merge before this structure); moving a row keeps it. Dates are
# partial ISO text ('2022' or '2022-09'), so both precisions compare correctly. source_run_id is the document
# run an accepted row came from.
records = Table(
    "records",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),  # userdata.RECORD_KINDS
    Column("title", Text),
    Column("organisation", Text),
    Column("location", Text),
    Column("start_date", Text),
    Column("end_date", Text),
    Column("ongoing", Boolean, nullable=False),
    Column("disclosure", Text, nullable=False, server_default="public"),  # 'public' or 'private'
    Column("part_of_id", Integer, ForeignKey("records.id"), index=True),  # the record that gives it context
    Column("context_lost_at", UTCDateTime),  # set when its part_of record was deleted, until relinked or dismissed
    Column("origin", Text, nullable=False),
    Column("source_run_id", Integer, ForeignKey("document_runs.id")),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

record_lines = Table(
    "record_lines",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("record_id", Integer, ForeignKey("records.id"), nullable=False, index=True),
    Column("position", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

# Exactly one of url and document_id is set.
record_sources = Table(
    "record_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("record_id", Integer, ForeignKey("records.id"), nullable=False, index=True),
    Column("position", Integer, nullable=False),
    Column("kind", Text, nullable=False),  # userdata.SOURCE_KINDS
    Column("url", Text),
    Column("document_id", Integer, ForeignKey("documents.id")),
    Column("origin", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
)

# A skill is in the profile when it has a claim. level_origin is 'model' or 'user', as skills.level_origin was.
claims = Table(
    "claims",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("skill_id", Integer, ForeignKey("skills.id"), nullable=False, unique=True),
    Column("level", Text, nullable=False),  # userdata.SKILL_LEVELS
    Column("level_origin", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("source_run_id", Integer, ForeignKey("document_runs.id")),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

# A claim's grounds: the records that show the skill, each with the quote naming it.
claim_records = Table(
    "claim_records",
    metadata,
    Column("claim_id", Integer, ForeignKey("claims.id"), nullable=False),
    Column("record_id", Integer, ForeignKey("records.id"), nullable=False, index=True),
    Column("quote", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    PrimaryKeyConstraint("claim_id", "record_id"),
)

highlights = Table(
    "highlights",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("text", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("source_run_id", Integer, ForeignKey("document_runs.id")),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

# A highlight's coverage of a claim; the quote names the skill in the highlight's text, when known.
highlight_claims = Table(
    "highlight_claims",
    metadata,
    Column("highlight_id", Integer, ForeignKey("highlights.id"), nullable=False),
    Column("claim_id", Integer, ForeignKey("claims.id"), nullable=False, index=True),
    Column("quote", Text),
    Column("origin", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    PrimaryKeyConstraint("highlight_id", "claim_id"),
)

# A merged skill's key, resolving to the skill it was merged into (profile side only: marks keep their skill).
skill_aliases = Table(
    "skill_aliases",
    metadata,
    Column("alias_key", Text, primary_key=True),  # userdata.name_key of the merged skill's name
    Column("skill_id", Integer, ForeignKey("skills.id"), nullable=False, index=True),
    Column("created_at", UTCDateTime, nullable=False),
)

profile_details = Table(
    "profile_details",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),  # userdata.DETAIL_KINDS
    Column("label", Text),  # e.g. "Email"
    Column("text", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

# Rejected suggestions and deleted (or edited-away) profile rows, by identity (userdata.identity_*), so document
# suggestions with that identity aren't offered.
profile_rejections = Table(
    "profile_rejections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),  # the identity's first part: 'record', 'claim', 'ground', ...
    Column("identity", Text, nullable=False, unique=True),
    Column("label", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
)

# The user's choice of link for a posting skill; skill_id NULL means "no link". Never judged again.
skill_link_overrides = Table(
    "skill_link_overrides",
    metadata,
    Column("posting_key", Text, primary_key=True),  # userdata.name_key of the posting skill
    Column("skill_id", Integer, ForeignKey("skills.id")),
    Column("relation", Text),  # 'same', 'specific', 'general' or 'related'; NULL with no link
    Column("created_at", UTCDateTime, nullable=False),
)

# A CV tailored for a posting (tailor.py), saved as a frozen copy: later profile edits never change it.
# created_at is the month printed in its header.
tailored_cvs = Table(
    "tailored_cvs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False, index=True),
    Column("method", Text, nullable=False),  # the ranking, e.g. 'cv-rank@1'
    Column("content_version", Integer, nullable=False),  # the payload shape cvdoc reads
    Column("match_score", Float),  # the posting's match score when saved; NULL with no posting skills
    Column("choice_json", Text, nullable=False),  # the budgets, counts and ticks it was proposed from
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

# One top-level item of a saved CV, in print order within its section. source_id names the profile row it was
# copied from, with no foreign key, so the CV outlives it; payload_json holds the copied field values
# (cvdoc.model), and a record printed under another travels inside its parent's payload.
tailored_cv_items = Table(
    "tailored_cv_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cv_id", Integer, ForeignKey("tailored_cvs.id"), nullable=False, index=True),
    Column("section", Text, nullable=False),  # 'header', 'goal', 'summary', 'highlights' or a record kind
    Column("position", Integer, nullable=False),
    Column("source_kind", Text, nullable=False),  # 'detail', 'highlight', 'record' or 'course_group'
    Column("source_id", Integer),
    Column("payload_json", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
)


# --- Derived data (model output), written only by enrich/derived.py. Rows are never edited. ---

# One extraction run of one snapshot. `pipeline` names every step and its version, e.g.
# "seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3"; equal text means comparable runs.
posting_enrichments = Table(
    "posting_enrichments",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, ForeignKey("postings.job_id"), nullable=False, index=True),
    Column("snapshot_id", Integer, ForeignKey("posting_snapshots.id"), nullable=False, index=True),
    Column("model", Text, nullable=False),
    Column("pipeline", Text, nullable=False),
    Column("status", Text, nullable=False),  # 'succeeded' or 'failed'
    Column("error", Text),
    Column("started_at", UTCDateTime, nullable=False),
    Column("finished_at", UTCDateTime, nullable=False),
    Column("output_json", Text, nullable=False),  # step trace: segments, raw outputs, attempts, timings
    Column("origin", Text, nullable=False, server_default="app"),  # 'app' (the job queue) or 'eval' (jobhunt eval)
)

# Offsets are into the snapshot's description_text and are set only for verified items.
enrichment_skills = Table(
    "enrichment_skills",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("enrichment_id", Integer, ForeignKey("posting_enrichments.id"), nullable=False, index=True),
    Column("position", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("key", Text, nullable=False),  # userdata.name_key(name)
    Column("importance", Text, nullable=False),  # 'required' or 'preferred', from the segment
    Column("kind", Text, nullable=False),  # 'technical', 'soft' or 'qualification' ('domain' in atomic@1 runs)
    Column("quote", Text, nullable=False),
    Column("start_offset", Integer),
    Column("end_offset", Integer),
    Column("verified", Boolean, nullable=False),
)

enrichment_salaries = Table(
    "enrichment_salaries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("enrichment_id", Integer, ForeignKey("posting_enrichments.id"), nullable=False, index=True),
    Column("position", Integer, nullable=False),
    Column("min_amount", Float),  # compared and displayed, never summed, so Float is enough
    Column("max_amount", Float),
    Column("currency", Text, nullable=False),
    Column("period", Text, nullable=False),
    Column("location", Text),
    Column("basis", Text, nullable=False),  # 'base', 'ote' or 'unclear'
    Column("quote", Text, nullable=False),
    Column("start_offset", Integer),
    Column("end_offset", Integer),
    Column("verified", Boolean, nullable=False),
)

# One extraction of a document for the profile. Its verified suggestions are profile_suggestions rows;
# output_json holds the step trace, with the unverified items.
document_runs = Table(
    "document_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("document_id", Integer, ForeignKey("documents.id"), nullable=False, index=True),
    Column("text_sha256", String(64), nullable=False),  # of the text the run read
    Column("model", Text, nullable=False),
    Column("pipeline", Text, nullable=False),  # e.g. "cvseg=caps@1 cvlines=llm@1 cvrecords=rules@1 ..."
    Column("status", Text, nullable=False),  # 'succeeded' or 'failed'
    Column("error", Text),
    Column("started_at", UTCDateTime, nullable=False),
    Column("finished_at", UTCDateTime, nullable=False),
    Column("output_json", Text, nullable=False),
)

# A verified suggestion of a document run, never edited. `position` counts within the run's suggestions of one
# kind; a claim's grounds and coverage and a part_of link name the run's records and highlights by it.
profile_suggestions = Table(
    "profile_suggestions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("document_runs.id"), nullable=False, index=True),
    Column("position", Integer, nullable=False),
    Column("kind", Text, nullable=False),  # 'record', 'claim', 'part_of' or 'highlight'
    Column("payload_json", Text, nullable=False),
)

# A skill name's embedding, computed once per model; vector is little-endian float32.
skill_embeddings = Table(
    "skill_embeddings",
    metadata,
    Column("model", Text, nullable=False),
    Column("text_key", Text, nullable=False),  # userdata.name_key of the embedded name
    Column("vector", LargeBinary, nullable=False),
    PrimaryKeyConstraint("model", "text_key"),
)

# One judgment of a posting skill against its shortlisted profile skills (candidates_json); the newest
# succeeded one per posting_key is in effect.
link_judgments = Table(
    "link_judgments",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("posting_key", Text, nullable=False, index=True),
    Column("posting_name", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("embed_model", Text, nullable=False),
    Column("pipeline", Text, nullable=False),
    Column("candidates_json", Text, nullable=False),  # [{"skill_id", "name", "similarity"}]
    Column("status", Text, nullable=False),  # 'succeeded' or 'failed'
    Column("error", Text),
    Column("created_at", UTCDateTime, nullable=False),
    Column("output_json", Text, nullable=False),
)

# Alternative phrasings of a skill's name (enrich/expand.py), embedded beside the name to find link candidates.
# A posting skill uses its newest succeeded expansion at a step; a profile skill the newest whose context
# equals its expansion context.
skill_expansions = Table(
    "skill_expansions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("side", Text, nullable=False),  # 'posting' or 'profile'
    Column("skill_key", Text, nullable=False),  # userdata.name_key of the skill's name
    Column("skill_name", Text, nullable=False),
    Column("context", Text),  # the quote shown with the name; NULL for none
    Column("step", Text, nullable=False),  # e.g. 'skill-expand@1'
    Column("model", Text, nullable=False),
    Column("status", Text, nullable=False),  # 'succeeded' or 'failed'
    Column("error", Text),
    Column("phrases_json", Text, nullable=False),  # ["phrasing", ...], cleaned
    Column("created_at", UTCDateTime, nullable=False),
    Column("output_json", Text, nullable=False),
    Index("ix_skill_expansions_lookup", "side", "skill_key", "step"),
)

link_relations = Table(
    "link_relations",
    metadata,
    Column("judgment_id", Integer, ForeignKey("link_judgments.id"), nullable=False),
    Column("skill_id", Integer, ForeignKey("skills.id"), nullable=False),
    Column("relation", Text, nullable=False),  # 'same', 'specific', 'general', 'related' or 'none'
    Column("similarity", Float, nullable=False),
    PrimaryKeyConstraint("judgment_id", "skill_id"),
)


# A judgment made by link measurement (enrich/link_eval.py), kept apart from link_judgments: only the
# measurement reads it, so it never decides a link. relations_json maps skill id to relation.
link_measurements = Table(
    "link_measurements",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("posting_key", Text, nullable=False, index=True),
    Column("posting_name", Text, nullable=False),
    Column("judge", Text, nullable=False),  # e.g. 'link-judge@6'
    Column("model", Text, nullable=False),
    Column("embed_model", Text, nullable=False),
    Column("candidates_json", Text, nullable=False),  # [{"skill_id", "name", "similarity", "pair"}], in order
    Column("status", Text, nullable=False),  # 'succeeded' or 'failed'
    Column("error", Text),
    Column("relations_json", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("output_json", Text, nullable=False),
)


# --- Operational data: the model work queue, written only by enrich/jobs.py. ---

# kind 'posting' sets job_id and snapshot_id, 'document' sets document_id, 'links' sets neither.
llm_jobs = Table(
    "llm_jobs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False, server_default="posting"),  # 'posting', 'document' or 'links'
    Column("job_id", Integer, ForeignKey("postings.job_id"), index=True),
    Column("snapshot_id", Integer, ForeignKey("posting_snapshots.id")),
    Column("document_id", Integer, ForeignKey("documents.id")),
    Column("model", Text, nullable=False),  # fixed at enqueue time, so a settings change leaves queued work alone
    Column("pipeline", Text, nullable=False),
    Column("status", Text, nullable=False, index=True),  # 'queued', 'running', 'done', 'failed' or 'cancelled'
    Column("error", Text),
    Column("enrichment_id", Integer, ForeignKey("posting_enrichments.id")),
    Column("document_run_id", Integer, ForeignKey("document_runs.id")),
    Column("queued_at", UTCDateTime, nullable=False),
    Column("started_at", UTCDateTime),
    Column("finished_at", UTCDateTime),
)

USER_TABLES = (
    posting_triage,
    tags,
    posting_tags,
    dismiss_reasons,
    posting_dismissals,
    posting_dismissal_reasons,
    skills,
    posting_skill_marks,
    companies,
    contacts,
    contact_emails,
    applications,
    application_events,
    documents,
    application_documents,
    application_contacts,
    rejected_suggestions,
    app_settings,
    records,
    record_lines,
    record_sources,
    claims,
    claim_records,
    highlights,
    highlight_claims,
    skill_aliases,
    profile_details,
    profile_rejections,
    skill_link_overrides,
    tailored_cvs,
    tailored_cv_items,
)

DERIVED_TABLES = (
    posting_enrichments,
    enrichment_skills,
    enrichment_salaries,
    document_runs,
    profile_suggestions,
    skill_embeddings,
    link_judgments,
    link_relations,
    skill_expansions,
    link_measurements,
)

OPERATIONAL_TABLES = (llm_jobs,)


def make_engine(url: str = DEFAULT_DB_URL, **kwargs) -> Engine:
    """Create an engine; a SQLite file's folder is created on demand."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, **kwargs)
        event.listen(engine, "connect", _sqlite_foreign_keys)
        return engine
    return create_engine(url, **kwargs)


def _sqlite_foreign_keys(dbapi_connection, _record) -> None:
    # Postgres always enforces foreign keys; make SQLite match.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db(engine: Engine) -> None:
    """Create the schema in an empty database, or migrate an older one to the current version."""
    from .migrate import upgrade  # migrations import this module

    upgrade(engine)
