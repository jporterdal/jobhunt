"""Posting list, detail, snapshot diff, capture download, import action and Insights (recommendations, answers)."""

from __future__ import annotations

import mimetypes
from io import BytesIO

from flask import Blueprint, abort, current_app, redirect, render_template, request, send_file, url_for
from sqlalchemy import select

from .. import prune, queries, recommend, userdata
from ..db import captures
from ..enrich import jobs
from ..importer import OUTCOMES, discover, import_files
from ..queries import DISMISSED_MODES, LABELLED_FILTERS, SORTS, STATUS_FILTERS, WORKPLACE_TYPES, ListFilters
from ..store import read_capture
from . import is_htmx, llm, reading, writing
from .triage import safe_next

bp = Blueprint("postings", __name__)


def bulk_context(conn, filters: ListFilters) -> dict:
    """The "Extract N postings" action for the listed postings, and the queue."""
    status = llm.current_status(conn)
    model, pipeline = jobs.current_pipeline(conn)
    return dict(
        extract_count=queries.unextracted_count(conn, filters, model, pipeline),
        llm_status=status,
        llm_unavailable=llm.unavailable_reason(status),
        queue=queries.queue_overview(conn),
    )


@bp.get("/")
def index():
    filters = ListFilters.from_args(request.args)
    with reading() as conn:
        rows = queries.posting_list(conn, filters)
        context = dict(
            rows=rows,
            filters=filters,
            all_tags=queries.all_tags(conn),
            sorts=SORTS,
            dismissed_modes=DISMISSED_MODES,
            workplace_types=WORKPLACE_TYPES,
            status_filters=STATUS_FILTERS,
            labelled_filters=LABELLED_FILTERS,
            section="postings",
            **bulk_context(conn, filters),
        )
    if is_htmx() and request.headers.get("HX-Target") == "posting-rows":
        # The extract count follows the filters, so its box comes along out of band.
        return render_template("postings/_rows.html", **context) + render_template(
            "llm/_bulk.html", oob=True, **context
        )
    return render_template("postings/list.html", **context)


def detail_context(conn, job_id: int) -> dict:
    detail = queries.posting_detail(conn, job_id)
    if detail is None:
        abort(404)
    return dict(
        d=detail,
        mark_quotes=[{"quote": m["quote"], "importance": m["importance"]} for m in detail["marks"]],
        **llm.panel_context(conn, job_id, request.args.get("run", type=int)),
        summary=recommend.posting_summary(conn, job_id),
        all_tags=queries.all_tags(conn),
        reasons=queries.all_dismiss_reasons(conn),
        all_skills=queries.all_skills(conn),
        manual_applications=[] if detail["application"] else queries.manual_applications(conn),
        cv_job_id=job_id,
        cv_list=queries.tailored_cvs_for_posting(conn, job_id),
        section="postings",
    )


@bp.get("/postings/<int:job_id>")
def detail(job_id: int):
    with reading() as conn:
        context = detail_context(conn, job_id)
    return render_template("postings/detail.html", **context)


@bp.get("/postings/<int:job_id>/captures/<int:capture_id>")
def download_capture(job_id: int, capture_id: int):
    with reading() as conn:
        row = conn.execute(
            select(captures.c.source_name).where(captures.c.id == capture_id, captures.c.job_id == job_id)
        ).first()
        if row is None:
            abort(404)
        raw = read_capture(conn, capture_id)
    mimetype = mimetypes.guess_type(row.source_name)[0] or "application/octet-stream"
    return send_file(BytesIO(raw), mimetype=mimetype, as_attachment=True, download_name=row.source_name)


@bp.get("/postings/<int:job_id>/diff")
def diff(job_id: int):
    old_id = request.args.get("old", type=int)
    new_id = request.args.get("new", type=int)
    with reading() as conn:
        detail = queries.posting_detail(conn, job_id)
        if detail is None or old_id is None or new_id is None:
            abort(404)
        result = queries.snapshot_diff(conn, job_id, old_id, new_id)
    if result is None:
        abort(404)
    return render_template("postings/diff.html", d=detail, diff=result, section="postings")


@bp.post("/import")
def import_inbox():
    inbox = current_app.config["INBOX"]
    if not inbox.is_dir():
        with reading() as conn:
            last_prune = prune.latest(conn, inbox)
        return render_template(
            "import_report.html", error=f"Inbox folder not found: {inbox}", inbox=inbox, last_prune=last_prune
        ), 404
    installed = current_app.config["PARSERS"]
    results = import_files(current_app.config["ENGINE"], discover(inbox, installed.parsers), inbox, installed.parsers)
    counts = {o: sum(r.outcome == o for r in results) for o in OUTCOMES}
    with reading() as conn:
        last_prune = prune.latest(conn, inbox)
    return render_template(
        "import_report.html", results=results, counts=counts, inbox=inbox, error=None, warnings=installed.errors,
        last_prune=last_prune,
    )


@bp.get("/insights")
def insights():
    chosen = recommend.workplace_choice(request.args.getlist("workplace"))
    with reading() as conn:
        found = recommend.recommendations(conn, chosen)
    # The page's own URL, from the parsed choice, so answers come back to the same filter.
    here = url_for("postings.insights", workplace=sorted(chosen)) if chosen else url_for("postings.insights")
    return render_template(
        "insights.html", r=found, here=here, workplace_types=WORKPLACE_TYPES, section="insights"
    )


@bp.post("/insights/skill")
def answer_skill():
    """"Have it" (at a level) or "don't have it" (`missing`) for a recommended skill: it joins the profile."""
    with writing() as conn:
        userdata.add_profile_skill(conn, request.form.get("name", ""), request.form.get("level", ""))
    return redirect(safe_next(url_for("postings.insights")), 303)
