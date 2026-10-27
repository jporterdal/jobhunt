"""Tailored CVs: the proposal for a posting (read-only; its choices live in the URL), saving it, a saved CV's page
with its edits, and the ODT export. Selection is in tailor.py, wording in cvdoc/layout.py, writes in userdata.py.
"""

from __future__ import annotations

from io import BytesIO

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for

from .. import queries, tailor, userdata
from ..cvdoc import layout, odt
from . import is_htmx, reading, writing

bp = Blueprint("cvs", __name__)

FILENAME_CHARS = 120


def cv_filename(company: str | None, title: str | None) -> str:
    """'CV - <company> - <title>.odt' with only letters, digits, spaces, '-', '_' and '.', at most FILENAME_CHARS."""
    raw = " - ".join(["CV", *(p for p in (company, title) if p)])
    stem = "".join(c for c in raw if c.isalnum() or c in " -_.")
    stem = " ".join(stem.split()).strip(" .")
    return stem[:FILENAME_CHARS - len(".odt")].rstrip(" .") + ".odt"


def _posting(conn, job_id: int) -> dict:
    posting = queries.posting_heading(conn, job_id)
    if posting is None:
        abort(404)
    return posting


@bp.get("/postings/<int:job_id>/cv")
def proposal(job_id: int):
    choice = tailor.Choice.from_args(request.args)
    with reading() as conn:
        posting = _posting(conn, job_id)
        p = tailor.propose(conn, job_id, choice)
    context = dict(posting=posting, p=p, cv=layout.build(p.content), L=layout, section="postings",
                   kinds=tailor.RANKED_KINDS)
    if is_htmx():
        return render_template("cvs/_proposal_body.html", **context)
    return render_template("cvs/proposal.html", **context)


@bp.post("/postings/<int:job_id>/cvs")
def save(job_id: int):
    # Ids only, never text from the browser: the proposal is made again here, inside the write.
    choice = tailor.Choice.from_args(request.form)
    with writing() as conn:
        _posting(conn, job_id)
        cv_id = userdata.save_tailored_cv(conn, job_id, tailor.propose(conn, job_id, choice))
    return redirect(url_for("cvs.saved", cv_id=cv_id), 303)


def _saved_or_404(conn, cv_id: int) -> dict:
    found = queries.tailored_cv(conn, cv_id)
    if found is None:
        abort(404)
    return found


@bp.get("/cvs/<int:cv_id>")
def saved(cv_id: int):
    with reading() as conn:
        found = _saved_or_404(conn, cv_id)
    return render_template("cvs/cv.html", s=found, cv=layout.build(found["content"]), L=layout, section="postings")


@bp.get("/cvs/<int:cv_id>.odt")
def export(cv_id: int):
    with reading() as conn:
        found = _saved_or_404(conn, cv_id)
    data = odt.write(layout.build(found["content"]))
    name = cv_filename(found["posting"]["company"], found["posting"]["title"])
    return send_file(BytesIO(data), mimetype=odt.MIMETYPE, as_attachment=True, download_name=name)


def _back(cv_id: int, anchor: str = ""):
    return redirect(url_for("cvs.saved", cv_id=cv_id) + anchor, 303)


@bp.post("/cvs/<int:cv_id>/items/<int:item_id>/move")
def move_item(cv_id: int, item_id: int):
    with writing() as conn:
        _saved_or_404(conn, cv_id)
        userdata.move_cv_item(conn, cv_id, item_id, request.form.get("direction", ""))
    return _back(cv_id, f"#item-{item_id}")


@bp.post("/cvs/<int:cv_id>/items/<int:item_id>/remove")
def remove_item(cv_id: int, item_id: int):
    with writing() as conn:
        _saved_or_404(conn, cv_id)
        userdata.remove_cv_item(conn, cv_id, item_id)
    return _back(cv_id, "#items")


@bp.post("/cvs/<int:cv_id>/delete")
def delete(cv_id: int):
    with writing() as conn:
        job_id = _saved_or_404(conn, cv_id)["cv"].job_id
        userdata.delete_tailored_cv(conn, cv_id)
    return redirect(url_for("postings.detail", job_id=job_id) + "#cvs", 303)
