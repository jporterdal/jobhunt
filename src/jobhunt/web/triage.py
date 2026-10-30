"""Ratings, tags, notes, dismissals, skill marks and levels, and the skills page."""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import queries, userdata
from ..db import postings, skills
from ..userdata import UserDataError
from . import is_htmx, reading, writing

bp = Blueprint("triage", __name__)


def _require_posting(conn, job_id: int) -> None:
    if conn.execute(select(postings.c.job_id).where(postings.c.job_id == job_id)).first() is None:
        abort(404)


def _detail_url(job_id: int) -> str:
    return url_for("postings.detail", job_id=job_id)


def safe_next(default: str) -> str:
    """A same-site path from the form's `next`, never an absolute or protocol-relative URL."""
    target = request.form.get("next", "")
    return target if target.startswith("/") and not target.startswith("//") else default


def _compact() -> bool:
    return request.form.get("compact") == "1"


def _fragment_or_redirect(job_id: int, template: str, **context):
    """htmx gets the re-rendered fragment; a plain form post goes back to the posting."""
    if is_htmx():
        return render_template(template, job_id=job_id, **context)
    return redirect(_detail_url(job_id), 303)


# --- Ratings, tags, notes ---


@bp.post("/postings/<int:job_id>/rating")
def rate(job_id: int):
    raw = request.form.get("value", "")
    if raw and not raw.isdigit():
        raise UserDataError("ratings run from 1 to 5")
    value = int(raw) if raw else None
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.set_rating(conn, job_id, request.form.get("field", ""), value)
        triage = queries.posting_detail(conn, job_id)["triage"]
    return _fragment_or_redirect(
        job_id, "triage/_ratings.html", interest=triage.interest, fit=triage.fit, compact=_compact()
    )


def _tags_response(conn, job_id: int):
    tags = queries.tags_by_posting(conn, [job_id]).get(job_id, [])
    return _fragment_or_redirect(job_id, "triage/_tags.html", tags=tags, compact=_compact())


@bp.post("/postings/<int:job_id>/tags")
def add_tag(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.add_tag(conn, job_id, request.form.get("name", ""))
        return _tags_response(conn, job_id)


@bp.post("/postings/<int:job_id>/tags/<int:tag_id>/remove")
def remove_tag(job_id: int, tag_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.remove_tag(conn, job_id, tag_id)
        return _tags_response(conn, job_id)


@bp.post("/postings/<int:job_id>/notes")
def save_notes(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.set_notes(conn, job_id, request.form.get("notes", ""))
        triage = queries.posting_detail(conn, job_id)["triage"]
    return _fragment_or_redirect(job_id, "triage/_notes.html", notes=triage.notes)


# --- Dismissals ---


@bp.post("/postings/<int:job_id>/dismiss")
def dismiss(job_id: int):
    reason_ids = [int(r) for r in request.form.getlist("reason") if r.isdigit()]
    with writing() as conn:
        _require_posting(conn, job_id)
        new_reason = request.form.get("new_reason", "").strip()
        if new_reason:
            reason_ids.append(userdata.add_dismiss_reason(conn, new_reason).id)
        userdata.dismiss(conn, job_id, reason_ids, request.form.get("comment"))
    return redirect(_detail_url(job_id), 303)


@bp.post("/postings/<int:job_id>/restore")
def restore(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.restore(conn, job_id)
    return redirect(_detail_url(job_id), 303)


# --- Skill marks and levels ---


@bp.post("/postings/<int:job_id>/marks")
def add_mark(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.add_skill_mark(
            conn,
            job_id,
            request.form.get("skill", ""),
            request.form.get("quote", ""),
            importance=request.form.get("importance") or None,
        )
    return redirect(_detail_url(job_id) + "#marks-panel", 303)


@bp.post("/postings/<int:job_id>/marks/<int:mark_id>/importance")
def set_importance(job_id: int, mark_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.set_mark_importance(conn, mark_id, request.form.get("importance") or None)
    return redirect(_detail_url(job_id) + "#marks-panel", 303)


@bp.post("/postings/<int:job_id>/labelled")
def set_labelled(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.set_skills_complete(
            conn, job_id, request.form.get("complete") == "1", choice=request.form.get("choice") or "auto"
        )
    return redirect(_detail_url(job_id) + "#marks-panel", 303)


@bp.post("/postings/<int:job_id>/eval-set")
def move_eval_set(job_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.move_eval_set(conn, job_id, request.form.get("set", ""))
    return redirect(_detail_url(job_id) + "#marks-panel", 303)


@bp.post("/postings/<int:job_id>/marks/<int:mark_id>/remove")
def remove_mark(job_id: int, mark_id: int):
    with writing() as conn:
        _require_posting(conn, job_id)
        userdata.remove_skill_mark(conn, mark_id)
    return redirect(_detail_url(job_id) + "#marks-panel", 303)


@bp.post("/skills/<int:skill_id>/level")
def set_level(skill_id: int):
    with writing() as conn:
        if conn.execute(select(skills.c.id).where(skills.c.id == skill_id)).first() is None:
            abort(404)
        userdata.set_skill_level(conn, skill_id, request.form.get("level") or None)
    return redirect(safe_next(url_for("triage.skills_page")), 303)


@bp.get("/skills")
def skills_page():
    with reading() as conn:
        overview = queries.skills_overview(conn)
    return render_template("skills.html", skills=overview, section="skills")
