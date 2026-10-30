"""Model features: status badge, settings, extraction and the queue, and accepting or rejecting suggestions.

Actions answer with a redirect to the page they came from; htmx swaps in the part it asked for with hx-select.
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import queries, recommend, userdata
from ..db import enrichment_skills, posting_enrichments, postings
from ..enrich import jobs, links
from ..enrich.ollama import Status
from ..enrich.pipeline import CURRENT_SKILLS, Unreachable, segmenters
from ..queries import ListFilters
from ..userdata import UserDataError
from . import list_url, reading, writing

bp = Blueprint("llm", __name__)


# --- Status ---


def current_status(conn) -> Status:
    client = current_app.config["OLLAMA"]
    model = userdata.get_setting(conn, "llm.model")
    if client is None:
        return Status("offline", model, "no Ollama address configured")
    return client.status(model)


def unavailable_reason(status: Status) -> str | None:
    """Why model actions are disabled, or None when they can run."""
    if status.state == "offline":
        return "Ollama is offline."
    if status.state == "no_model":
        return "Choose a model in Settings."
    if status.state == "missing":
        return f"The selected model {status.model} is not installed."
    return None


def require_ready(conn) -> None:
    reason = unavailable_reason(current_status(conn))
    if reason:
        raise UserDataError(reason.rstrip("."))


@bp.get("/llm/status")
def status():
    with reading() as conn:
        state = current_status(conn)
    return render_template("llm/_status.html", status=state)


# --- Settings ---


def _settings_context(conn, error: str | None = None) -> dict:
    client = current_app.config["OLLAMA"]
    models, embed_models, offline = [], [], False
    if client is not None:
        try:
            installed = client.models()
            models = [m.name for m in installed if m.generates_text]
            embed_models = links.embed_choices(installed)
        except Unreachable:
            offline = True
    else:
        offline = True
    stored = userdata.settings(conn)
    return dict(
        settings=stored,
        models=models,
        embed_models=embed_models,
        embed_model=links.resolve_embed_model(stored["llm.embed_model"], embed_models),
        offline=offline,
        segmenters=list(segmenters()),
        skills_method=CURRENT_SKILLS,
        eval_sets=queries.eval_set_counts(conn),
        ollama_url=client.url if client is not None else None,
        num_ctx_range=userdata.NUM_CTX_RANGE,
        holdout_share_range=userdata.HOLDOUT_SHARE_RANGE,
        error=error,
        section="settings",
    )


@bp.get("/settings")
def settings_page():
    with reading() as conn:
        context = _settings_context(conn)
    return render_template("settings.html", **context)


@bp.post("/settings")
def save_settings():
    if "skills" in request.form:
        raise UserDataError(f"the skill extraction method is not a setting; the app uses {CURRENT_SKILLS}")
    with writing() as conn:
        model = request.form.get("model")
        if model is not None:
            context = _settings_context(conn)
            if context["offline"]:
                raise UserDataError("Ollama is offline, so the model list is unavailable")
            if model not in context["models"]:
                raise UserDataError(f"{model!r} is not an installed text model")
            userdata.set_setting(conn, "llm.model", model)
        embed_model = request.form.get("embed_model")
        if embed_model is not None:
            if embed_model not in _settings_context(conn)["embed_models"]:
                raise UserDataError(f"{embed_model!r} is not an installed embedding model")
            userdata.set_setting(conn, "llm.embed_model", embed_model)
        userdata.set_setting(conn, "llm.num_ctx", request.form.get("num_ctx", ""))
        userdata.set_setting(conn, "llm.segmenter", request.form.get("segmenter", ""))
    return redirect(url_for("llm.settings_page"), 303)


@bp.post("/settings/eval")
def save_eval():
    """The holdout share; apart from the model form, so it saves while Ollama is offline."""
    with writing() as conn:
        userdata.set_setting(conn, "eval.holdout_share", request.form.get("holdout_share", ""))
    return redirect(url_for("llm.settings_page") + "#evaluation", 303)


# --- Extraction and the queue ---


def _require_posting(conn, job_id: int) -> None:
    if conn.execute(select(postings.c.job_id).where(postings.c.job_id == job_id)).first() is None:
        abort(404)


def detail_url(job_id: int, run_id: int | None = None) -> str:
    return url_for("postings.detail", job_id=job_id, run=run_id) + "#model-says"


@bp.post("/postings/<int:job_id>/extract")
def extract(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        require_ready(conn)
        jobs.enqueue(conn, job_id)
    return redirect(detail_url(job_id), 303)


@bp.post("/extract")
def extract_list():
    filters = ListFilters.from_args(request.form)
    with writing() as conn:
        require_ready(conn)
        jobs.enqueue_unextracted(conn, filters)
    return redirect(list_url(filters), 303)


@bp.get("/llm/queue")
def queue():
    with reading() as conn:
        overview = queries.queue_overview(conn)
    # 286 tells htmx to stop polling; the fragment then has no trigger either.
    return render_template("llm/_queue.html", queue=overview), 200 if overview["busy"] else 286


@bp.post("/llm/queue/cancel")
def cancel_queue():
    with writing() as conn:
        jobs.cancel_all(conn)
    target = request.form.get("next", "")
    return redirect(target if target.startswith("/") and not target.startswith("//") else "/", 303)


@bp.get("/postings/<int:job_id>/model-says")
def panel(job_id: int):
    with reading() as conn:
        _require_posting(conn, job_id)
        context = panel_context(conn, job_id, request.args.get("run", type=int))
        summary = recommend.posting_summary(conn, job_id)
    return render_template("llm/_panel.html", **context) + render_template(
        "postings/_skill_summary.html", summary=summary, oob=True
    )


def panel_context(conn, job_id: int, run_id: int | None = None) -> dict:
    status = current_status(conn)
    return dict(
        job_id=job_id,
        panel=queries.enrichment_panel(conn, job_id, run_id),
        llm_job=queries.posting_job(conn, job_id),
        llm_status=status,
        llm_unavailable=unavailable_reason(status),
    )


# --- Suggestions ---


def _run_arg() -> int | None:
    return request.form.get("run", type=int)


@bp.post("/suggestions/<int:item_id>/accept")
def accept(item_id: int):
    with writing() as conn:
        job_id = conn.execute(
            select(posting_enrichments.c.job_id)
            .join(enrichment_skills, enrichment_skills.c.enrichment_id == posting_enrichments.c.id)
            .where(enrichment_skills.c.id == item_id)
        ).scalar()
        if job_id is None:
            abort(404)
        userdata.accept_suggestion(conn, item_id)
    return redirect(detail_url(job_id, _run_arg()), 303)


@bp.post("/postings/<int:job_id>/suggestions/accept-all")
def accept_all(job_id: int):
    run_id = _run_arg()
    if run_id is None:
        abort(400)
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.accept_all(conn, job_id, run_id, request.form.get("importance", ""))
    return redirect(detail_url(job_id, run_id), 303)


@bp.post("/postings/<int:job_id>/rejections")
def reject(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.reject_suggestion(conn, job_id, request.form.get("skill", ""), request.form.get("reason", ""))
    return redirect(detail_url(job_id, _run_arg()), 303)


@bp.post("/postings/<int:job_id>/rejections/reason")
def rejection_reason(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.set_rejection_reason(conn, job_id, request.form.get("skill", ""), request.form.get("reason", ""))
    return redirect(detail_url(job_id, _run_arg()), 303)


@bp.post("/postings/<int:job_id>/rejections/delete")
def unreject(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.unreject_suggestion(conn, job_id, request.form.get("skill", ""))
    return redirect(detail_url(job_id, _run_arg()), 303)
