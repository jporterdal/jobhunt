"""The profile: details, records (lines, sources, context, disclosure), claims (levels, grounds, aliases) and
highlights; document suggestions; remembered rejections; and the links page.

Actions answer with a redirect to the page they came from; htmx swaps in the part it asked for with hx-select.
"""

from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from .. import queries, userdata
from ..enrich import jobs, links
from ..enrich.cv import PART_OF_GUIDELINE
from ..enrich.pipeline import Unreachable
from ..queries import SUGGESTION_KINDS
from ..userdata import (
    DETAIL_KINDS,
    DISCLOSURES,
    LINK_RELATIONS,
    RECORD_KINDS,
    SKILL_LEVELS,
    SOURCE_KINDS,
    UserDataError,
)
from . import llm, reading, writing

bp = Blueprint("profile", __name__)


def _back(anchor: str = ""):
    return redirect(url_for("profile.profile_page") + anchor, 303)


def _form_int(name: str) -> int | None:
    raw = request.form.get(name, "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise UserDataError(f"{name.replace('_', ' ')} must be a whole number")
    return int(raw)


def _required_int(name: str) -> int:
    value = _form_int(name)
    if value is None:
        raise UserDataError(f"choose a {name.removesuffix('_id').replace('_', ' ')}")
    return value


def _record_fields() -> dict:
    form = request.form
    return {
        "kind": form.get("kind"),
        "title": form.get("title"),
        "organisation": form.get("organisation"),
        "location": form.get("location"),
        "start_date": form.get("start_date"),
        "end_date": form.get("end_date"),
        "ongoing": form.get("ongoing") == "1",
        "disclosure": form.get("disclosure") or "public",
    }


def _record_anchor() -> str:
    record_id = _form_int("record_id")
    return f"#record-{record_id}" if record_id else "#records"


# --- The profile page ---


@bp.get("/profile")
def profile_page():
    with reading() as conn:
        data = queries.profile(conn)
        linked = queries.linked_posting_skills(conn)
        pending = queries.profile_suggestions(conn)["count"]
        rejections = len(queries.profile_rejections_list(conn))
    return render_template(
        "profile/profile.html", p=data, linked=linked, pending=pending, rejections=rejections,
        record_kinds=RECORD_KINDS, detail_kinds=DETAIL_KINDS, source_kinds=SOURCE_KINDS, disclosures=DISCLOSURES,
        levels=SKILL_LEVELS, guideline=PART_OF_GUIDELINE, section="profile",
    )


# Details


@bp.post("/profile/details")
def add_detail():
    form = request.form
    with writing() as conn:
        detail_id = userdata.add_detail(conn, form.get("kind", ""), form.get("text", ""), form.get("label"))
    return _back(f"#detail-{detail_id}")


@bp.post("/profile/details/<int:detail_id>/edit")
def edit_detail(detail_id: int):
    form = request.form
    with writing() as conn:
        userdata.update_detail(conn, detail_id, form.get("kind", ""), form.get("text", ""), form.get("label"))
    return _back(f"#detail-{detail_id}")


@bp.post("/profile/details/<int:detail_id>/delete")
def delete_detail(detail_id: int):
    with writing() as conn:
        userdata.delete_detail(conn, detail_id)
    return _back("#details")


# Records


@bp.post("/profile/records")
def add_record():
    with writing() as conn:
        record_id = userdata.add_record(conn, _record_fields())
    return _back(f"#record-{record_id}")


@bp.post("/profile/records/<int:record_id>/edit")
def edit_record(record_id: int):
    with writing() as conn:
        userdata.update_record(conn, record_id, _record_fields())
    return _back(f"#record-{record_id}")


@bp.post("/profile/records/<int:record_id>/delete")
def delete_record(record_id: int):
    with writing() as conn:
        userdata.delete_record(conn, record_id)
    return _back("#records")


@bp.post("/profile/records/<int:record_id>/part-of")
def set_part_of(record_id: int):
    with writing() as conn:
        userdata.set_part_of(conn, record_id, _form_int("part_of_id"))
    return _back(f"#record-{record_id}")


@bp.post("/profile/records/<int:record_id>/dismiss-lost-context")
def dismiss_lost_context(record_id: int):
    with writing() as conn:
        userdata.dismiss_lost_context(conn, record_id)
    return _back(f"#record-{record_id}")


@bp.post("/profile/records/<int:record_id>/disclosure")
def set_disclosure(record_id: int):
    with writing() as conn:
        userdata.set_disclosure(conn, record_id, request.form.get("disclosure", ""))
    return _back(f"#record-{record_id}")


# Lines and sources


@bp.post("/profile/records/<int:record_id>/lines")
def add_line(record_id: int):
    with writing() as conn:
        userdata.add_line(conn, record_id, request.form.get("text", ""))
    return _back(f"#record-{record_id}")


@bp.post("/profile/lines/<int:line_id>/edit")
def edit_line(line_id: int):
    with writing() as conn:
        userdata.update_line(conn, line_id, request.form.get("text", ""))
    return _back(_record_anchor())


@bp.post("/profile/lines/<int:line_id>/move")
def move_line(line_id: int):
    with writing() as conn:
        userdata.move_line(conn, line_id, request.form.get("direction", ""))
    return _back(_record_anchor())


@bp.post("/profile/lines/<int:line_id>/delete")
def delete_line(line_id: int):
    with writing() as conn:
        userdata.delete_line(conn, line_id)
    return _back(_record_anchor())


@bp.post("/profile/records/<int:record_id>/sources")
def add_source(record_id: int):
    form = request.form
    with writing() as conn:
        userdata.add_source(conn, record_id, form.get("url"), _form_int("document_id"), form.get("kind") or None)
    return _back(f"#record-{record_id}")


@bp.post("/profile/sources/<int:source_id>/edit")
def edit_source(source_id: int):
    with writing() as conn:
        userdata.update_source(conn, source_id, request.form.get("url"), request.form.get("kind") or None)
    return _back(_record_anchor())


@bp.post("/profile/sources/<int:source_id>/delete")
def delete_source(source_id: int):
    with writing() as conn:
        userdata.delete_source(conn, source_id)
    return _back(_record_anchor())


# Skills, grounds and aliases


@bp.post("/profile/skills")
def add_skill():
    with writing() as conn:
        skill_id = userdata.add_profile_skill(conn, request.form.get("name", ""), request.form.get("level", ""))
    return _back(f"#skill-{skill_id}")


@bp.post("/profile/skills/<int:skill_id>/rename")
def rename_skill(skill_id: int):
    with writing() as conn:
        userdata.rename_skill(conn, skill_id, request.form.get("name", ""))
    return _back(f"#skill-{skill_id}")


@bp.post("/profile/skills/<int:skill_id>/remove")
def remove_skill(skill_id: int):
    with writing() as conn:
        userdata.remove_profile_skill(conn, skill_id)
    return _back("#skills")


@bp.post("/profile/skills/<int:skill_id>/grounds")
def add_ground(skill_id: int):
    with writing() as conn:
        userdata.add_ground(conn, skill_id, _required_int("record_id"), request.form.get("quote"))
    return _back(f"#skill-{skill_id}")


@bp.post("/profile/skills/<int:skill_id>/grounds/<int:record_id>/remove")
def remove_ground(skill_id: int, record_id: int):
    with writing() as conn:
        userdata.remove_ground(conn, skill_id, record_id)
    return _back(f"#skill-{skill_id}")


@bp.post("/profile/skills/<int:skill_id>/merge")
def merge_skill(skill_id: int):
    kept = _required_int("into")
    with writing() as conn:
        userdata.merge_skill(conn, skill_id, kept)
    return _back(f"#skill-{kept}")


@bp.post("/profile/aliases/remove")
def remove_alias():
    with writing() as conn:
        userdata.remove_alias(conn, request.form.get("alias_key", ""))
    skill_id = _form_int("skill_id")
    return _back(f"#skill-{skill_id}" if skill_id else "#skills")


# Highlights


@bp.post("/profile/highlights")
def add_highlight():
    with writing() as conn:
        highlight_id = userdata.add_highlight(conn, request.form.get("text", ""))
    return _back(f"#highlight-{highlight_id}")


@bp.post("/profile/highlights/<int:highlight_id>/edit")
def edit_highlight(highlight_id: int):
    with writing() as conn:
        userdata.update_highlight(conn, highlight_id, request.form.get("text", ""))
    return _back(f"#highlight-{highlight_id}")


@bp.post("/profile/highlights/<int:highlight_id>/delete")
def delete_highlight(highlight_id: int):
    with writing() as conn:
        userdata.delete_highlight(conn, highlight_id)
    return _back("#highlights")


@bp.post("/profile/highlights/<int:highlight_id>/coverage")
def add_coverage(highlight_id: int):
    with writing() as conn:
        userdata.add_coverage(conn, highlight_id, _required_int("skill_id"), request.form.get("quote"))
    return _back(f"#highlight-{highlight_id}")


@bp.post("/profile/highlights/<int:highlight_id>/coverage/<int:skill_id>/remove")
def remove_coverage(highlight_id: int, skill_id: int):
    with writing() as conn:
        userdata.remove_coverage(conn, highlight_id, skill_id)
    return _back(f"#highlight-{highlight_id}")


# --- Document suggestions ---


@bp.get("/profile/suggestions")
def suggestions_page():
    kind = request.args.get("kind", "")
    accepted = request.args.get("accepted", "")
    with reading() as conn:
        offered = queries.profile_suggestions(conn)
    return render_template(
        "profile/suggestions.html", s=offered, kinds=SUGGESTION_KINDS, guideline=PART_OF_GUIDELINE,
        accepted=int(accepted) if accepted.isdigit() and kind in SUGGESTION_KINDS else None, accepted_kind=kind,
        section="profile",
    )


def _to_suggestions(group: str, **args):
    return redirect(url_for("profile.suggestions_page", **args) + f"#group-{group}", 303)


@bp.post("/profile/suggestions/<int:suggestion_id>/accept")
def accept_suggestion(suggestion_id: int):
    with writing() as conn:
        kind = userdata.accept_profile_suggestion(conn, suggestion_id)
    return _to_suggestions(kind)


@bp.post("/profile/suggestions/<int:suggestion_id>/reject")
def reject_suggestion(suggestion_id: int):
    with writing() as conn:
        userdata.reject_profile_suggestion(conn, suggestion_id)
    return _to_suggestions(request.form.get("kind", ""))


@bp.post("/profile/suggestions/accept-all")
def accept_all():
    kind = request.form.get("kind", "")
    with writing() as conn:
        accepted = userdata.accept_all_profile_suggestions(conn, kind)
    return _to_suggestions(kind, kind=kind, accepted=accepted)


# --- Remembered rejections ---


@bp.get("/profile/rejections")
def rejections_page():
    with reading() as conn:
        rows = queries.profile_rejections_list(conn)
    return render_template("profile/rejections.html", rejections=rows, section="profile")


@bp.post("/profile/rejections/<int:rejection_id>/forget")
def forget(rejection_id: int):
    with writing() as conn:
        userdata.forget_rejection(conn, rejection_id)
    return redirect(url_for("profile.rejections_page"), 303)


# --- Links ---


def _embedding_notice(conn) -> str | None:
    """Why link judging waits, or None when it can run."""
    client = current_app.config["OLLAMA"]
    if client is None:
        return "No Ollama address is configured, so links can't be judged."
    try:
        model = links.embed_model(conn, client)
    except Unreachable:
        return "Ollama is offline: link judging waits until it is back."
    if model is None:
        chosen = userdata.get_setting(conn, "llm.embed_model")
        if chosen:
            return f"The embedding model {chosen} is not installed, so link judging waits. Choose another in Settings."
        return (
            "No embedding model is installed, so link judging waits. Pull nomic-embed-text, or choose one in Settings."
        )
    return None


@bp.get("/profile/links")
def links_page():
    with reading() as conn:
        rows = queries.links_overview(conn)
        skills = queries.profile_skills(conn)
        stale = queries.stale_override_count(conn)
        notice = _embedding_notice(conn)
        status = llm.current_status(conn)
    return render_template(
        "profile/links.html", rows=rows, skills=skills, relations=LINK_RELATIONS, notice=notice, stale=stale,
        llm_unavailable=llm.unavailable_reason(status), section="profile",
    )


@bp.post("/profile/links/override")
def override():
    choice = request.form.get("skill", "")
    with writing() as conn:
        if choice == "none":
            userdata.set_link_override(conn, request.form.get("posting_skill", ""), None)
        elif choice.isdigit():
            userdata.set_link_override(
                conn, request.form.get("posting_skill", ""), int(choice), request.form.get("relation")
            )
        else:
            raise UserDataError("choose a profile skill or no link")
    return redirect(url_for("profile.links_page"), 303)


@bp.post("/profile/links/clear")
def clear_override():
    with writing() as conn:
        userdata.clear_link_override(conn, request.form.get("posting_skill", ""))
    return redirect(url_for("profile.links_page"), 303)


@bp.post("/profile/links/rejudge")
def rejudge():
    with writing() as conn:
        llm.require_ready(conn)
        if jobs.enqueue_links(conn, everything=True) is None:
            raise UserDataError("add skills to the profile first")
    return redirect(url_for("profile.links_page"), 303)
