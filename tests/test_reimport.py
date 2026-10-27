"""Imports must never create, change or delete user-authored data."""

import shutil
from datetime import date

from sqlalchemy import select

from jobhunt import documents, userdata
from jobhunt.db import (
    DERIVED_TABLES,
    USER_TABLES,
    dismiss_reasons,
    enrichment_skills,
    posting_skill_marks,
    posting_snapshots,
)
from jobhunt.importer import import_files

from .conftest import posting_file

FIXTURE = posting_file("data-automation.json")


def user_data(engine) -> dict:
    with engine.connect() as conn:
        return {
            t.name: sorted(conn.execute(select(t)).all(), key=lambda r: tuple(map(str, r)))
            for t in USER_TABLES
        }


def add_user_data(engine, documents_dir, job: int) -> None:
    with engine.begin() as conn:
        userdata.set_rating(conn, job, "interest", 4)
        userdata.set_rating(conn, job, "fit", 3)
        userdata.set_notes(conn, job, "Ask about **visa**")
        userdata.add_tag(conn, job, "ml")
        userdata.add_skill_mark(conn, job, "Automation", "drives data automation")
        skill_id = conn.execute(select(posting_skill_marks.c.skill_id)).scalar_one()
        userdata.set_skill_level(conn, skill_id, "proficient")
        other = conn.execute(select(dismiss_reasons.c.id).where(dismiss_reasons.c.key == "other")).scalar_one()
        userdata.dismiss(conn, job, [other], "parking it")
        userdata.restore(conn, job)

        app_id = userdata.start_application(conn, job)
        userdata.add_event(conn, app_id, "applied", date(2026, 9, 28), "via careers site")
        userdata.set_next_action(conn, app_id, "Follow up", date(2026, 10, 9))
        stored = documents.store_upload(documents_dir, b"my cv", "cv.txt")
        userdata.link_document(conn, app_id, userdata.add_document(conn, stored, "CV v3", "cv"))
        company = userdata.get_or_create_company(conn, "Example Bank")
        contact_id = userdata.save_contact(conn, None, "Jane Doe", ["jane@acme.example"], company_id=company.id)
        userdata.link_contact(conn, app_id, contact_id)
        userdata.set_setting(conn, "llm.model", "gemma4:12b")
        userdata.reject_suggestion(conn, job, "Communication", "not-a-skill")
        userdata.set_skills_complete(conn, job, True)
        add_profile(conn, stored, job)


def add_profile(conn, stored, job: int) -> None:
    """An accepted document suggestion, records with lines and sources, a context link, claims with grounds, a
    highlight covering one, an alias, details, a rejection and a link override."""
    from jobhunt.enrich import derived
    from jobhunt.enrich.pipeline import DocumentResult

    now = userdata.utcnow()
    document_id = userdata.add_document(conn, stored, "CV for the profile", "cv")
    suggestions = {
        "record": [
            {
                "kind": "degree",
                "title": "PhD",
                "organisation": "Example University",
                "location": None,
                "start_date": None,
                "end_date": "2022",
                "ongoing": False,
                "lines": ["Thesis: search"],
                "sources": [],
            }
        ],
        "claim": [{"name": "Search", "level": "expert", "grounds": [{"record": 0, "quote": "search"}], "coverage": []}],
        "part_of": [],
        "highlight": [],
    }
    derived.save_document_run(
        conn, document_id, "f" * 64, "gemma4:12b", "p", DocumentResult("succeeded", None, now, now, suggestions, {})
    )
    userdata.accept_all_profile_suggestions(conn, "record")
    userdata.accept_all_profile_suggestions(conn, "claim")
    project = userdata.add_record(conn, {"kind": "project", "title": "jobhunt"})
    userdata.add_line(conn, project, "jobhunt, in Python")
    userdata.add_source(conn, project, "https://github.com/x/jobhunt")
    userdata.set_part_of(conn, project, userdata.add_record(conn, {"kind": "other", "title": "Side work"}))
    python = userdata.add_profile_skill(conn, "Python", "proficient")
    userdata.add_ground(conn, python, project, "Python")
    highlight = userdata.add_highlight(conn, "8+ years with Python")
    userdata.add_coverage(conn, highlight, python, "Python")
    userdata.merge_skill(conn, userdata.add_profile_skill(conn, "Python 3", "familiar"), python)
    userdata.add_detail(conn, "name", "Jane Doe")
    userdata.delete_line(conn, userdata.add_line(conn, project, "an old line"))
    userdata.set_link_override(conn, "Automation", python, "related")
    save_cv(conn, job)


def save_cv(conn, job: int) -> int:
    """A tailored CV saved for the posting, as the CV page saves one."""
    from jobhunt import tailor

    return userdata.save_tailored_cv(conn, job, tailor.propose(conn, job))


def test_user_data_survives_reimport(engine, tmp_path):
    first = tmp_path / "first.json"
    shutil.copyfile(FIXTURE, first)
    [result] = import_files(engine, [first])
    assert result.outcome == "new"

    add_user_data(engine, tmp_path / "documents", result.job_id)
    before = user_data(engine)
    assert all(before.values()), [name for name, rows in before.items() if not rows]

    changed = tmp_path / "changed.json"
    raw = FIXTURE.read_bytes()
    changed.write_bytes(raw.replace(b"This role drives", b"This role now drives"))
    assert [r.outcome for r in import_files(engine, [changed])] == ["updated"]

    with engine.connect() as conn:
        assert len(conn.execute(select(posting_snapshots)).all()) == 2
    assert user_data(engine) == before  # the saved CV's rows too ("Re-capture after saving")


def derived_data(engine) -> dict:
    with engine.connect() as conn:
        return {t.name: conn.execute(select(t).order_by(*t.primary_key.columns)).all() for t in DERIVED_TABLES}


def test_model_data_survives_reimport(engine, tmp_path):
    from jobhunt.enrich import jobs
    from jobhunt.queries import enrichment_panel

    from .fakes import FakeLLM, label_lines, skill

    first = tmp_path / "first.json"
    shutil.copyfile(FIXTURE, first)
    [result] = import_files(engine, [first])
    job = result.job_id
    with engine.begin() as conn:
        userdata.set_setting(conn, "llm.model", "gemma4:12b")
        jobs.enqueue(conn, job)
    llm = FakeLLM(
        {
            "lines": [label_lines({"data lineage": "required", "governance": "required", "LangChain": "preferred"})],
            "skills": [
                {"skills": [skill(1, "Data lineage", "data lineage"), skill(2, "Data governance", "data governance")]},
                {"skills": [skill(1, "LangChain", "LangChain")]},
            ],
        }
    )
    assert jobs.run_next(engine, llm) == "done"
    with engine.begin() as conn:
        accept = conn.execute(
            select(enrichment_skills.c.id).where(enrichment_skills.c.name == "Data lineage")
        ).scalar_one()
        mark_id = userdata.accept_suggestion(conn, accept)
        userdata.set_mark_importance(conn, mark_id, "preferred")
        userdata.reject_suggestion(conn, job, "LangChain", "not-a-skill")
        userdata.set_skills_complete(conn, job, True)
    before_user, before_derived = user_data(engine), derived_data(engine)

    changed = tmp_path / "changed.json"
    raw = FIXTURE.read_bytes()
    changed.write_bytes(raw.replace(b"This role drives", b"This role now drives"))
    assert [r.outcome for r in import_files(engine, [changed])] == ["updated"]

    assert user_data(engine) == before_user
    assert derived_data(engine) == before_derived
    with engine.connect() as conn:
        panel = enrichment_panel(conn, job)
    assert panel["stale"] and not panel["acceptable"]
