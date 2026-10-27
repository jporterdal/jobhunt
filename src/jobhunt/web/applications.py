"""Applications, events, the board, documents, companies and contacts."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from flask import Blueprint, abort, current_app, redirect, render_template, request, send_file, url_for

from .. import documents, queries, userdata
from ..enrich import jobs
from ..userdata import DOCUMENT_KINDS, EVENT_KINDS, UserDataError
from . import llm, reading, writing

bp = Blueprint("applications", __name__)


def _date(name: str, default: date | None = None) -> date | None:
    raw = request.form.get(name, "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise UserDataError(f"{raw!r} is not a date (use YYYY-MM-DD)") from None


def _int(name: str) -> int:
    raw = request.form.get(name, "")
    if not raw.isdigit():
        raise UserDataError(f"missing {name.replace('_', ' ')}")
    return int(raw)


def _to_application(app_id: int, anchor: str = ""):
    return redirect(url_for("applications.application", app_id=app_id) + anchor, 303)


# --- Applications ---


@bp.get("/applications")
def board():
    with reading() as conn:
        data = queries.applications_board(conn)
    return render_template("applications/board.html", board=data, section="applications")


@bp.get("/applications/new")
def new_application():
    return render_template("applications/new.html", section="applications")


@bp.post("/applications")
def create_application():
    with writing() as conn:
        app_id = userdata.create_application(
            conn, request.form.get("title", ""), request.form.get("company", ""), request.form.get("url")
        )
    return _to_application(app_id)


@bp.post("/postings/<int:job_id>/application")
def start_from_posting(job_id: int):
    with writing() as conn:
        app_id = userdata.start_application(conn, job_id)
    return _to_application(app_id)


@bp.post("/postings/<int:job_id>/link-application")
def link_posting_from_detail(job_id: int):
    app_id = _int("app_id")
    with writing() as conn:
        userdata.link_application(conn, app_id, job_id)
    return _to_application(app_id)


@bp.get("/applications/<int:app_id>")
def application(app_id: int):
    with reading() as conn:
        detail = queries.application_detail(conn, app_id)
        if detail is None:
            abort(404)
        company = queries.company_by_name(conn, detail["app"]["company"])
        all_companies = queries.all_companies(conn)
        posting = detail["posting"]
        cv_list = queries.tailored_cvs_for_posting(conn, posting["job_id"]) if posting else []
    return render_template(
        "applications/application.html",
        a=detail,
        event_kinds=EVENT_KINDS,
        document_kinds=DOCUMENT_KINDS,
        companies=all_companies,
        company_id=company.id if company else None,
        today=date.today(),
        cv_job_id=posting["job_id"] if posting else None,
        cv_list=cv_list,
        section="applications",
    )


@bp.post("/applications/<int:app_id>/edit")
def edit_application(app_id: int):
    form = request.form
    with writing() as conn:
        userdata.update_application(
            conn,
            app_id,
            form.get("title", ""),
            form.get("company", ""),
            form.get("url"),
            form.get("compensation_notes"),
        )
    return _to_application(app_id)


@bp.post("/applications/<int:app_id>/next-action")
def next_action(app_id: int):
    with writing() as conn:
        userdata.set_next_action(conn, app_id, request.form.get("next_action"), _date("next_action_due"))
    return _to_application(app_id)


@bp.post("/applications/<int:app_id>/events")
def add_event(app_id: int):
    with writing() as conn:
        userdata.add_event(
            conn, app_id, request.form.get("kind", ""), _date("event_date", date.today()), request.form.get("note")
        )
    return _to_application(app_id, "#events")


@bp.post("/applications/<int:app_id>/events/<int:event_id>/delete")
def delete_event(app_id: int, event_id: int):
    with writing() as conn:
        userdata.delete_event(conn, app_id, event_id)
    return _to_application(app_id, "#events")


@bp.post("/applications/<int:app_id>/documents")
def link_document(app_id: int):
    with writing() as conn:
        userdata.link_document(conn, app_id, _int("document_id"))
    return _to_application(app_id, "#documents")


@bp.post("/applications/<int:app_id>/documents/<int:document_id>/unlink")
def unlink_document(app_id: int, document_id: int):
    with writing() as conn:
        userdata.unlink_document(conn, app_id, document_id)
    return _to_application(app_id, "#documents")


@bp.post("/applications/<int:app_id>/contacts")
def link_contact(app_id: int):
    with writing() as conn:
        userdata.link_contact(conn, app_id, _int("contact_id"))
    return _to_application(app_id, "#contacts")


@bp.post("/applications/<int:app_id>/contacts/<int:contact_id>/unlink")
def unlink_contact(app_id: int, contact_id: int):
    with writing() as conn:
        userdata.unlink_contact(conn, app_id, contact_id)
    return _to_application(app_id, "#contacts")


# --- Documents ---


@bp.get("/documents")
def documents_page():
    with reading() as conn:
        docs = queries.documents_list(conn)
    return render_template(
        "applications/documents.html", docs=docs, document_kinds=DOCUMENT_KINDS, section="applications"
    )


@bp.post("/documents")
def upload_document():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise UserDataError("choose a file to upload")
    if request.form.get("kind", "other") not in DOCUMENT_KINDS:
        raise UserDataError(f"kind must be one of {', '.join(DOCUMENT_KINDS)}")
    stored = documents.store_upload(
        current_app.config["DOCUMENTS_DIR"], upload.read(), upload.filename, upload.mimetype
    )
    with writing() as conn:
        kind = request.form.get("kind", "other")
        document_id = userdata.add_document(conn, stored, request.form.get("label", ""), kind)
        if kind == "cv" and stored.text_content and userdata.get_setting(conn, "llm.model"):
            jobs.enqueue_document(conn, document_id)  # a CV goes into the profile without being asked
        app_id = request.form.get("app_id", "")
        if app_id.isdigit():
            userdata.link_document(conn, int(app_id), document_id)
            return _to_application(int(app_id), "#documents")
    return redirect(url_for("applications.document", document_id=document_id), 303)


@bp.get("/documents/<int:document_id>")
def document(document_id: int):
    with reading() as conn:
        detail = queries.document_detail(conn, document_id)
    if detail is None:
        abort(404)
    present = documents.path_for(current_app.config["DOCUMENTS_DIR"], detail["doc"].sha256).is_file()
    with reading() as conn:
        status = llm.current_status(conn)
    return render_template(
        "applications/document.html", d=detail, present=present, llm_unavailable=llm.unavailable_reason(status),
        section="applications",
    )


@bp.post("/documents/<int:document_id>/add-to-profile")
def add_to_profile(document_id: int):
    with writing() as conn:
        if queries.document_detail(conn, document_id) is None:
            abort(404)
        llm.require_ready(conn)
        jobs.enqueue_document(conn, document_id)
    return redirect(url_for("applications.document", document_id=document_id), 303)


@bp.get("/documents/<int:document_id>/download")
def download_document(document_id: int):
    with reading() as conn:
        detail = queries.document_detail(conn, document_id)
    if detail is None:
        abort(404)
    doc = detail["doc"]
    data = documents.read_bytes(current_app.config["DOCUMENTS_DIR"], doc.sha256)
    if data is None:
        abort(404)
    return send_file(BytesIO(data), mimetype=doc.media_type, as_attachment=True, download_name=doc.original_filename)


# --- Companies and contacts ---


@bp.get("/companies")
def companies():
    with reading() as conn:
        rows = queries.companies_overview(conn)
    return render_template(
        "applications/companies.html", companies=rows, name=request.args.get("name", ""), section="companies"
    )


@bp.get("/companies/lookup")
def company_lookup():
    """Where a company name on a posting or application leads: its record, or the form to create one."""
    name = request.args.get("name", "")
    with reading() as conn:
        company = queries.company_by_name(conn, name) if name.strip() else None
    if company is not None:
        return redirect(url_for("applications.company", company_id=company.id))
    return redirect(url_for("applications.companies", name=name) + "#new-company")


@bp.post("/companies")
def create_company():
    with writing() as conn:
        company = userdata.get_or_create_company(conn, request.form.get("name", ""))
    return redirect(url_for("applications.company", company_id=company.id), 303)


@bp.get("/companies/<int:company_id>")
def company(company_id: int):
    with reading() as conn:
        page = queries.company_page(conn, company_id)
    if page is None:
        abort(404)
    return render_template("applications/company.html", c=page, section="companies")


@bp.post("/companies/<int:company_id>/edit")
def edit_company(company_id: int):
    form = request.form
    with writing() as conn:
        userdata.update_company(
            conn, company_id, form.get("name", ""), form.get("website_url"), form.get("careers_url"), form.get("notes")
        )
    return redirect(url_for("applications.company", company_id=company_id), 303)


def _contact_fields() -> dict:
    form = request.form
    company_id = form.get("company_id", "")
    return dict(
        name=form.get("name", ""),
        emails=form.get("emails", "").replace(",", "\n").splitlines(),
        role=form.get("role"),
        profile_url=form.get("profile_url"),
        notes=form.get("notes"),
        company_id=int(company_id) if company_id.isdigit() else None,
    )


@bp.post("/contacts")
def create_contact():
    with writing() as conn:
        contact_id = userdata.save_contact(conn, None, **_contact_fields())
        app_id = request.form.get("app_id", "")
        if app_id.isdigit():
            userdata.link_contact(conn, int(app_id), contact_id)
            return _to_application(int(app_id), "#contacts")
    return redirect(url_for("applications.contact", contact_id=contact_id), 303)


@bp.get("/contacts/<int:contact_id>")
def contact(contact_id: int):
    with reading() as conn:
        detail = queries.contact_detail(conn, contact_id)
        all_companies = queries.all_companies(conn)
    if detail is None:
        abort(404)
    return render_template("applications/contact.html", d=detail, companies=all_companies, section="companies")


@bp.post("/contacts/<int:contact_id>/edit")
def edit_contact(contact_id: int):
    with writing() as conn:
        userdata.save_contact(conn, contact_id, **_contact_fields())
    return redirect(url_for("applications.contact", contact_id=contact_id), 303)
