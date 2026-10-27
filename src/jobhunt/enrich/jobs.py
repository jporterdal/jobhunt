"""The llm_jobs queue (its only writer) and the worker thread that runs it inside `serve`.

A job extracts a posting, extracts a document (storing suggestions for the profile), or judges skill links.
Jobs run oldest first across kinds; a links job waits while no embedding model is chosen or installed.

Model calls happen outside any transaction; each state change is its own short transaction. Cancelling a
running job marks it cancelled at once (finished_at stays NULL while its current step finishes: "cancelling");
the worker sees that between steps and stores nothing.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import UTC, datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from ..db import claims, documents, llm_jobs, posting_snapshots
from ..store import latest_snapshot
from ..userdata import UserDataError, get_setting
from . import cv, derived, links
from .pipeline import (
    CURRENT_SKILLS,
    Cancelled,
    StepFailed,
    Unreachable,
    pipeline_id,
    run_pipeline,
    steps_for,
    steps_from_id,
)

log = logging.getLogger(__name__)

ACTIVE = ("queued", "running")
IDLE_WAIT = 5
OFFLINE_BACKOFF = 10

# Set by enqueue so the worker starts promptly instead of at its next timeout.
WAKE = threading.Event()


def utcnow() -> datetime:
    return datetime.now(UTC)


def current_pipeline(conn: Connection) -> tuple[str | None, str]:
    """(model, pipeline id) from the stored settings and the app's skill extractor."""
    steps = steps_for(get_setting(conn, "llm.segmenter"), CURRENT_SKILLS)
    return get_setting(conn, "llm.model"), pipeline_id(steps)


def active_job(conn: Connection, job_id: int):
    return conn.execute(
        select(llm_jobs).where(llm_jobs.c.job_id == job_id, llm_jobs.c.status.in_(ACTIVE))
    ).first()


def enqueue(conn: Connection, job_id: int, model: str | None = None, pipeline: str | None = None,
            now: datetime | None = None) -> tuple[int, bool]:
    """Queue extraction of the posting's latest snapshot; (job id, added). A posting with a queued or
    running job keeps that one. Model and pipeline default to the current settings and are fixed here."""
    existing = active_job(conn, job_id)
    if existing is not None:
        return existing.id, False
    if model is None or pipeline is None:
        model, pipeline = current_pipeline(conn)
    if not model:
        raise UserDataError("choose a model in Settings first")
    snapshot = latest_snapshot(conn, job_id)
    if snapshot is None:
        raise UserDataError("no such posting")
    new_id = conn.execute(
        insert(llm_jobs).values(
            kind="posting", job_id=job_id, snapshot_id=snapshot.id, model=model, pipeline=pipeline, status="queued",
            queued_at=now or utcnow(),
        )
    ).inserted_primary_key[0]
    WAKE.set()
    return new_id, True


def enqueue_document(conn: Connection, document_id: int, now: datetime | None = None) -> tuple[int, bool]:
    """Queue extracting a document's suggestions for the profile with the selected model; (job id, added). A
    document with a queued or running extraction keeps that one."""
    model = get_setting(conn, "llm.model")
    if not model:
        raise UserDataError("choose a model in Settings first")
    doc = conn.execute(select(documents.c.id, documents.c.text_content).where(documents.c.id == document_id)).first()
    if doc is None:
        raise UserDataError("no such document")
    if not doc.text_content:
        raise UserDataError("the document has no extracted text to add to the profile")
    existing = conn.execute(
        select(llm_jobs.c.id).where(llm_jobs.c.document_id == document_id, llm_jobs.c.status.in_(ACTIVE))
    ).first()
    if existing is not None:
        return existing.id, False
    new_id = conn.execute(
        insert(llm_jobs).values(
            kind="document", document_id=document_id, model=model, pipeline=cv.pipeline_id(), status="queued",
            queued_at=now or utcnow(),
        )
    ).inserted_primary_key[0]
    WAKE.set()
    return new_id, True


def profile_has_skills(conn: Connection) -> bool:
    return conn.execute(select(claims.c.id).limit(1)).first() is not None


def enqueue_links(conn: Connection, everything: bool = False, now: datetime | None = None) -> int | None:
    """Queue link judging; the job's id, or None when there is nothing to judge with (no chat model chosen, or
    no profile skills). Changes coalesce: a queued links job already covers them (it plans when it runs), while
    a running one may have planned before the change, so another is queued. `everything` re-judges every
    posting skill without an override, and widens a queued job to do so."""
    model = get_setting(conn, "llm.model")
    if not model or not profile_has_skills(conn):
        return None
    pipeline = links.PIPELINE + (links.ALL_SCOPE if everything else "")
    queued = conn.execute(
        select(llm_jobs).where(llm_jobs.c.kind == "links", llm_jobs.c.status == "queued").order_by(llm_jobs.c.id)
    ).first()
    if queued is not None:
        if everything and queued.pipeline != pipeline:
            conn.execute(update(llm_jobs).where(llm_jobs.c.id == queued.id).values(pipeline=pipeline))
        return queued.id
    new_id = conn.execute(
        insert(llm_jobs).values(
            kind="links", model=model, pipeline=pipeline, status="queued", queued_at=now or utcnow()
        )
    ).inserted_primary_key[0]
    WAKE.set()
    return new_id


def enqueue_links_if_outdated(engine: Engine) -> int | None:
    """At worker start: queue link judging when some posting skill's latest judgment was made by another linking
    method than the current one (links.PIPELINE), so a new method version re-judges without waiting for an
    unrelated change. The job's id, or None."""
    with engine.begin() as conn:
        return enqueue_links(conn) if links.outdated(conn) else None


def enqueue_unextracted(conn: Connection, filters) -> int:
    """Queue every listed, non-dismissed posting with no successful run for its latest snapshot with the
    current model and pipeline; the number queued (queries.unextracted_count gives it beforehand)."""
    from ..queries import unextracted_ids

    model, pipeline = current_pipeline(conn)
    ids = unextracted_ids(conn, filters, model, pipeline)
    now = utcnow()
    return sum(enqueue(conn, job_id, model, pipeline, now)[1] for job_id in ids)


def cancel_all(conn: Connection, now: datetime | None = None) -> int:
    """Cancel queued jobs, and the running one before its next step. The number cancelled."""
    now = now or utcnow()
    queued = conn.execute(
        update(llm_jobs).where(llm_jobs.c.status == "queued").values(status="cancelled", finished_at=now)
    ).rowcount
    running = conn.execute(
        update(llm_jobs).where(llm_jobs.c.status == "running").values(status="cancelled")
    ).rowcount
    return queued + running


def recover(engine: Engine) -> None:
    """At worker start: jobs left running go back to queued; a cancel that never finished is finished."""
    with engine.begin() as conn:
        conn.execute(update(llm_jobs).where(llm_jobs.c.status == "running").values(status="queued", started_at=None))
        conn.execute(
            update(llm_jobs)
            .where(llm_jobs.c.status == "cancelled", llm_jobs.c.finished_at.is_(None))
            .values(finished_at=utcnow())
        )


def has_queued(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).where(llm_jobs.c.status == "queued")).scalar_one() > 0


def _waiting_links_embed(engine: Engine, client) -> str | None:
    """The embedding model a links job would use, asked of the server only when a links job is queued."""
    with engine.connect() as conn:
        queued_links = conn.execute(
            select(llm_jobs.c.id).where(llm_jobs.c.status == "queued", llm_jobs.c.kind == "links").limit(1)
        ).first()
        if queued_links is None or client is None:
            return None
        return links.embed_model(conn, client)


def _claim(engine: Engine, client=None):
    """(job, num_ctx, embedding model) for the oldest queued job that can run, now running; None when nothing
    can. A links job waits (is skipped, not failed) while no embedding model is chosen or installed."""
    embed = _waiting_links_embed(engine, client)
    with engine.begin() as conn:
        for job in conn.execute(select(llm_jobs).where(llm_jobs.c.status == "queued").order_by(llm_jobs.c.id)).all():
            if job.kind == "links" and embed is None:
                continue
            claimed = conn.execute(
                update(llm_jobs)
                .where(llm_jobs.c.id == job.id, llm_jobs.c.status == "queued")
                .values(status="running", started_at=utcnow())
            ).rowcount
            if not claimed:
                return None
            return job, get_setting(conn, "llm.num_ctx"), embed
    return None


def _still_running(engine: Engine, job_id: int) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(llm_jobs.c.status).where(llm_jobs.c.id == job_id)).scalar() == "running"


def _finish(engine: Engine, job_id: int, **values) -> None:
    with engine.begin() as conn:
        conn.execute(update(llm_jobs).where(llm_jobs.c.id == job_id).values(finished_at=utcnow(), **values))


def _cancelled_meanwhile(conn: Connection, job_id: int) -> bool:
    """True (and the cancel finished) when the job was cancelled during its last step: nothing is stored."""
    if conn.execute(select(llm_jobs.c.status).where(llm_jobs.c.id == job_id)).scalar() == "running":
        return False
    conn.execute(update(llm_jobs).where(llm_jobs.c.id == job_id).values(finished_at=utcnow()))
    return True


def _run_posting(engine: Engine, client, job, num_ctx: int, embed) -> str:
    with engine.connect() as conn:
        text = conn.execute(
            select(posting_snapshots.c.description_text).where(posting_snapshots.c.id == job.snapshot_id)
        ).scalar_one()
    steps = steps_from_id(job.pipeline)
    llm = client.for_model(job.model, num_ctx)
    result = run_pipeline(text, llm, steps, should_stop=lambda: not _still_running(engine, job.id))
    with engine.begin() as conn:
        if _cancelled_meanwhile(conn, job.id):
            return "cancelled"
        run_id = derived.save_run(conn, job.job_id, job.snapshot_id, job.model, job.pipeline, result, "app")
        final = "done" if result.status == "succeeded" else "failed"
        conn.execute(
            update(llm_jobs)
            .where(llm_jobs.c.id == job.id)
            .values(status=final, error=result.error, enrichment_id=run_id, finished_at=utcnow())
        )
        if final == "done":
            enqueue_links(conn)  # the posting's skills may have changed
    return final


def _run_document(engine: Engine, client, job, num_ctx: int, embed) -> str:
    cv.check_pipeline(job.pipeline)
    with engine.connect() as conn:
        text = conn.execute(select(documents.c.text_content).where(documents.c.id == job.document_id)).scalar_one()
    if not text:
        raise UserDataError("the document has no extracted text")
    llm = client.for_model(job.model, num_ctx)
    result = cv.run_document(text, llm, should_stop=lambda: not _still_running(engine, job.id))
    with engine.begin() as conn:
        if _cancelled_meanwhile(conn, job.id):
            return "cancelled"
        # Only suggestions are stored: the profile, and so link judging, waits for the user to accept them.
        run_id = derived.save_document_run(
            conn, job.document_id, hashlib.sha256(text.encode()).hexdigest(), job.model, job.pipeline, result
        )
        final = "done" if result.status == "succeeded" else "failed"
        conn.execute(
            update(llm_jobs)
            .where(llm_jobs.c.id == job.id)
            .values(status=final, error=result.error, document_run_id=run_id, finished_at=utcnow())
        )
    return final


def _run_links(engine: Engine, client, job, num_ctx: int, embed: str) -> str:
    try:
        result = links.judge_links(
            engine, client, job.model, num_ctx, embed, job.pipeline.endswith(links.ALL_SCOPE),
            should_stop=lambda: not _still_running(engine, job.id),
        )
    except StepFailed as exc:  # embedding failed: nothing was stored
        _finish(engine, job.id, status="failed", error=f"{exc.step or 'embed'}: {exc.message}")
        return "failed"
    error = f"{result.failed} of {result.planned} judgments failed" if result.failed else None
    with engine.begin() as conn:
        if _cancelled_meanwhile(conn, job.id):
            return "cancelled"
        conn.execute(
            update(llm_jobs).where(llm_jobs.c.id == job.id).values(status="done", error=error, finished_at=utcnow())
        )
    return "done"


RUNNERS = {"posting": _run_posting, "document": _run_document, "links": _run_links}


def run_next(engine: Engine, client) -> str | None:
    """Run the oldest queued job that can run; its final status, or None when there was none.

    `client.for_model(model, num_ctx)` gives the LLM; links jobs also use `client.models()` and
    `client.embed()`. Unreachable puts the job back to queued and is raised again so the worker can back off.
    """
    claimed = _claim(engine, client)
    if claimed is None:
        return None
    job, num_ctx, embed = claimed
    try:
        return RUNNERS[job.kind](engine, client, job, num_ctx, embed)
    except Cancelled:
        _finish(engine, job.id)
        return "cancelled"
    except Unreachable:
        with engine.begin() as conn:
            conn.execute(
                update(llm_jobs).where(llm_jobs.c.id == job.id, llm_jobs.c.status == "running")
                .values(status="queued", started_at=None)
            )
        raise
    except Exception as exc:  # a bug or an unavailable pipeline: fail the job rather than retry it forever
        log.exception("%s job %s failed", job.kind, job.id)
        _finish(engine, job.id, status="failed", error=f"{type(exc).__name__}: {exc}")
        return "failed"


class Worker(threading.Thread):
    """The single background worker inside `serve`. It only calls the configured Ollama and stores results."""

    def __init__(self, engine: Engine, client, idle_wait: float = IDLE_WAIT, offline_backoff: float = OFFLINE_BACKOFF):
        super().__init__(name="jobhunt-llm-worker", daemon=True)
        self.engine = engine
        self.client = client
        self.idle_wait = idle_wait
        self.offline_backoff = offline_backoff
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        WAKE.set()

    def run(self) -> None:
        recover(self.engine)
        enqueue_links_if_outdated(self.engine)
        while not self._stop_event.is_set():
            try:
                if not has_queued(self.engine):
                    WAKE.wait(self.idle_wait)
                    WAKE.clear()
                    continue
                self.client.version()  # reachable? queued jobs wait rather than fail
                if run_next(self.engine, self.client) is None:  # only waiting links jobs are queued
                    WAKE.wait(self.idle_wait)
                    WAKE.clear()
            except Unreachable:
                self._stop_event.wait(self.offline_backoff)
            except Exception:
                log.exception("extraction worker error")
                self._stop_event.wait(self.offline_backoff)
