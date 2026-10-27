"""The profile as a knowledge base: records, lines, sources, context links, disclosure, claims and levels, grounds,
highlights, aliases, details and remembered rejections (userdata), and the profile read model (queries), on each
configured database."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from jobhunt import queries, userdata
from jobhunt.db import (
    claim_records,
    claims,
    highlight_claims,
    llm_jobs,
    posting_skill_marks,
    profile_rejections,
    record_lines,
    record_sources,
    records,
    skill_aliases,
    skill_link_overrides,
    skills,
)
from jobhunt.documents import StoredFile
from jobhunt.userdata import UserDataError

from .conftest import add_posting
from .test_userdata import JOB, OTHER, T1, T2, T3, count, write

THIRD = 3  # the third posting the db fixture imports
T4 = T3 + timedelta(days=1)


@pytest.fixture
def db(engine):
    add_posting(engine)
    add_posting(engine, "senior-ai-engineer.json")
    assert add_posting(engine, "innovation-lab.json") == THIRD
    return engine


def rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table).order_by(*table.primary_key.columns)).all()


def add_document(engine, label="CV", kind="cv", sha="a" * 64, text="text"):
    stored = StoredFile(sha, 10, f"{label}.odt", "application/vnd.oasis.opendocument.text", text, "extracted")
    return write(engine, userdata.add_document, stored, label, kind)


def record(engine, title, kind="project", organisation=None, start=None, end=None, ongoing=False, now=T1, **more):
    fields = {"kind": kind, "title": title, "organisation": organisation, "start_date": start, "end_date": end,
              "ongoing": ongoing, **more}
    return write(engine, userdata.add_record, fields, now)


def skill_id(engine, key):
    with engine.connect() as conn:
        return conn.execute(select(skills.c.id).where(skills.c.key == key)).scalar_one()


def claim(engine, key):
    with engine.connect() as conn:
        return conn.execute(
            select(claims).join(skills, skills.c.id == claims.c.skill_id).where(skills.c.key == key)
        ).first()


def grounds_of(engine, key):
    c = claim(engine, key)
    return [] if c is None else sorted(g.record_id for g in rows(engine, claim_records) if g.claim_id == c.id)


def rejected(engine):
    return {r.identity for r in rows(engine, profile_rejections)}


def page_claim(engine, key):
    with engine.connect() as conn:
        p = queries.profile(conn)
    return next(c for _, group in p["claims"] for c in group if c["key"] == key)


def page_record(engine, record_id):
    with engine.connect() as conn:
        p = queries.profile(conn)
    return next(r for _, group in p["records"] for r in group if r["id"] == record_id)


def kinds_and_titles(engine):
    with engine.connect() as conn:
        p = queries.profile(conn)
    return [(kind, [(r["title"], r["start_date"], r["end_date"]) for r in group]) for kind, group in p["records"]]


# --- Records, lines and sources (3.1) ---


def test_a_project_with_lines_and_sources(db):
    parking = record(db, "city-parking")
    for text in ("Parking enforcement tool", "Technologies: Python, Flask", "Won 'Best Design'"):
        write(db, userdata.add_line, parking, text)
    write(db, userdata.add_source, parking, "https://github.com/janedoe/city-parking")
    record(db, "tidyplots", end="2024")
    r = page_record(db, parking)
    assert [line["text"] for line in r["lines"]] == [
        "Parking enforcement tool",
        "Technologies: Python, Flask",
        "Won 'Best Design'",
    ]
    assert [(s["kind"], s["url"]) for s in r["sources"]] == [("repo", "https://github.com/janedoe/city-parking")]
    assert kinds_and_titles(db) == [("project", [("tidyplots", None, "2024"), ("city-parking", None, None)])]


def test_one_record_per_term_taught(db):
    for start, end in (("2025-01", "2025-04"), ("2026-09", "2026-12"), ("2026-01", "2026-04")):
        record(db, "Sessional Instructor, COMP 1000", "course", "Example Polytechnic", start, end)
    assert kinds_and_titles(db) == [("course", [
        ("Sessional Instructor, COMP 1000", "2026-09", "2026-12"),
        ("Sessional Instructor, COMP 1000", "2026-01", "2026-04"),
        ("Sessional Instructor, COMP 1000", "2025-01", "2025-04"),
    ])]


def test_ongoing_records_first_and_ties_in_creation_order(db):
    record(db, "ended", end="2026")
    record(db, "jobhunt", start="2025-03", ongoing=True)
    record(db, "same year, later month", end="2026-05")
    record(db, "tie", end="2026")
    [(_, projects)] = kinds_and_titles(db)
    assert [t for t, _, _ in projects] == ["jobhunt", "same year, later month", "ended", "tie"]


def test_records_grouped_in_kind_order(db):
    record(db, "Best Design", "award")
    record(db, "PhD", "degree")
    record(db, "Professor", "role")
    assert [kind for kind, _ in kinds_and_titles(db)] == ["role", "degree", "award"]


def test_changing_a_records_kind(db):
    best = record(db, "Best Design", "other")
    write(db, userdata.update_record, best, {"kind": "award", "title": "Best Design"}, T2)
    assert kinds_and_titles(db) == [("award", [("Best Design", None, None)])]
    assert rows(db, records)[0].origin == "user"


def test_record_needs_a_title_or_organisation_and_valid_fields(db):
    for fields in (
        {"kind": "project"},
        {"kind": "hobby", "title": "x"},
        {"kind": "project", "title": "x", "end_date": "May"},
    ):
        with pytest.raises(UserDataError):
            write(db, userdata.add_record, fields)


def test_lines_edit_and_move_keep_or_change_origin(db):
    parking = record(db, "city-parking")
    first = write(db, userdata.add_line, parking, "first")
    second = write(db, userdata.add_line, parking, "second")
    with db.begin() as conn:
        conn.execute(update(record_lines).values(origin="suggestion"))
    write(db, userdata.move_line, second, "up")
    assert [(line.text, line.origin) for line in sorted(rows(db, record_lines), key=lambda line: line.position)] == [
        ("second", "suggestion"), ("first", "suggestion"),
    ]
    write(db, userdata.update_line, first, "first, edited", T2)
    assert {line.text: line.origin for line in rows(db, record_lines)}["first, edited"] == "user"
    write(db, userdata.move_line, second, "up")  # already first: nothing happens
    write(db, userdata.delete_line, first)
    assert [line.text for line in rows(db, record_lines)] == ["second"]


def test_sources_by_address_or_document(db):
    paper = record(db, "EXCONF paper", "publication")
    write(db, userdata.add_source, paper, "https://doi.org/10.5555/3600000.3600001")
    write(db, userdata.add_source, paper, "https://example.org/slides")
    doc = add_document(db)
    write(db, userdata.add_source, paper, None, doc)
    assert [(s.kind, s.url, s.document_id) for s in rows(db, record_sources)] == [
        ("doi", "https://doi.org/10.5555/3600000.3600001", None),
        ("site", "https://example.org/slides", None),
        ("document", None, doc),
    ]
    with pytest.raises(UserDataError):
        write(db, userdata.add_source, paper, None, None)
    source_id = rows(db, record_sources)[1].id
    write(db, userdata.update_source, source_id, "https://example.org/talk", "other")
    assert (rows(db, record_sources)[1].kind, rows(db, record_sources)[1].url) == ("other", "https://example.org/talk")
    write(db, userdata.delete_source, source_id)
    assert len(rows(db, record_sources)) == 2


def test_deleting_a_record(db):
    unix = record(db, "Unix admin")
    other = record(db, "Homelab")
    write(db, userdata.add_line, unix, "ran servers")
    write(db, userdata.add_line, unix, "wrote scripts")
    write(db, userdata.add_source, unix, "https://example.org")
    linux = write(db, userdata.add_profile_skill, "Linux", "proficient")
    write(db, userdata.add_ground, linux, unix)
    write(db, userdata.add_ground, linux, other)
    write(db, userdata.delete_record, unix, T2)
    assert [r.id for r in rows(db, records)] == [other]
    assert rows(db, record_lines) == [] and rows(db, record_sources) == []
    assert grounds_of(db, "linux") == [other]
    assert userdata.identity_record("project", "Unix admin", None, None, None) in rejected(db)


# --- Context links and disclosure (3.2) ---


def test_thesis_part_of_the_degree(db):
    phd = record(db, "PhD Computer Science", "degree")
    thesis = record(db, "PhD thesis", "publication")
    write(db, userdata.set_part_of, thesis, phd)
    assert page_record(db, thesis)["part_of"] == {"id": phd, "label": "PhD Computer Science"}
    assert page_record(db, phd)["dependents"] == [{"id": thesis, "label": "PhD thesis"}]


def test_context_does_not_ground(db):
    paper = record(db, "EXCONF 2024 paper", "publication")
    tidyplots = record(db, "tidyplots")
    write(db, userdata.set_part_of, tidyplots, paper)
    numpy = write(db, userdata.add_profile_skill, "NumPy", "proficient")
    write(db, userdata.add_ground, numpy, tidyplots)
    assert grounds_of(db, "numpy") == [tidyplots]
    assert page_record(db, paper)["grounds"] == []


def test_cycle_refused(db):
    paper = record(db, "EXCONF 2024 paper", "publication")
    tidyplots = record(db, "tidyplots")
    write(db, userdata.set_part_of, tidyplots, paper)
    with pytest.raises(UserDataError, match="part of itself"):
        write(db, userdata.set_part_of, paper, tidyplots)
    with pytest.raises(UserDataError, match="part of itself"):
        write(db, userdata.set_part_of, paper, paper)
    assert {r.id: r.part_of_id for r in rows(db, records)} == {paper: None, tidyplots: paper}


def test_deleting_a_context_record(db):
    parking = record(db, "city-parking")
    best = record(db, "Best Design", "award")
    write(db, userdata.set_part_of, best, parking)
    write(db, userdata.delete_record, parking, T2)
    [kept] = rows(db, records)
    assert (kept.id, kept.part_of_id, kept.context_lost_at) == (best, None, T2)
    assert page_record(db, best)["context_lost"] is True
    write(db, userdata.dismiss_lost_context, best)
    assert page_record(db, best)["context_lost"] is False


def test_relinking_clears_lost_context_and_clearing_a_link_is_remembered(db):
    parking = record(db, "city-parking")
    best = record(db, "Best Design", "award")
    write(db, userdata.set_part_of, best, parking)
    other = record(db, "hackathon", "event")
    write(db, userdata.delete_record, other)
    write(db, userdata.set_part_of, best, None)
    assert userdata.identity_part_of(
        userdata.identity_record("award", "Best Design", None, None, None),
        userdata.identity_record("project", "city-parking", None, None, None),
    ) in rejected(db)
    new_parent = record(db, "city-parking v2")
    with db.begin() as conn:
        conn.execute(update(records).where(records.c.id == best).values(context_lost_at=T2))
    write(db, userdata.set_part_of, best, new_parent)
    assert page_record(db, best)["context_lost"] is False


def test_private_project(db):
    app = record(db, "hobby web app", disclosure="private")
    django = write(db, userdata.add_profile_skill, "Django", "proficient")
    write(db, userdata.add_ground, django, app)
    assert grounds_of(db, "django") == [app]
    r = page_record(db, app)
    assert (r["effective_disclosure"], r["private_through_context"]) == ("private", False)
    assert page_claim(db, "django")["ungrounded"] is False


def test_private_through_context(db):
    project = record(db, "secret project")
    award = record(db, "an award", "award")
    write(db, userdata.set_part_of, award, project)
    write(db, userdata.set_disclosure, project, "private")
    r = page_record(db, award)
    assert (r["disclosure"], r["effective_disclosure"], r["private_through_context"]) == ("public", "private", True)
    with pytest.raises(UserDataError):
        write(db, userdata.set_disclosure, project, "secret")


# --- Claims and levels (3.3) ---


def test_adding_a_skill_by_hand(db):
    docker = write(db, userdata.add_profile_skill, "Docker", "proficient")
    c = claim(db, "docker")
    assert (c.skill_id, c.level, c.level_origin, c.origin) == (docker, "proficient", "user", "user")


def test_removing_a_skill_keeps_posting_marks_and_highlights(db):
    for job in (JOB, OTHER, THIRD):
        write(db, userdata.add_skill_mark, job, "Python", "Python")
    python = skill_id(db, "python")
    write(db, userdata.set_skill_level, python, "expert")
    numpy = write(db, userdata.add_profile_skill, "NumPy", "proficient")
    highlight = write(db, userdata.add_highlight, "8+ years with Python (incl. NumPy)")
    write(db, userdata.add_coverage, highlight, python, "Python")
    write(db, userdata.add_coverage, highlight, numpy, "NumPy")
    write(db, userdata.add_ground, python, record(db, "tidyplots"))

    write(db, userdata.remove_profile_skill, python)
    assert claim(db, "python") is None and grounds_of(db, "python") == []
    assert count(db, posting_skill_marks) == 3
    with db.connect() as conn:
        [h] = queries.profile(conn)["highlights"]
    assert [c["name"] for c in h["claims"]] == ["NumPy"]
    assert userdata.identity_claim("python") in rejected(db)


def test_setting_a_level(db):
    for job in (JOB, OTHER):
        write(db, userdata.add_skill_mark, job, "Kubernetes", "Kubernetes")
    write(db, userdata.set_skill_level, skill_id(db, "kubernetes"), "missing")
    assert claim(db, "kubernetes").level == "missing"
    with db.connect() as conn:
        levels = [m["level"] for job in (JOB, OTHER) for m in queries.posting_detail(conn, job)["marks"]]
    assert levels == ["missing", "missing"]
    write(db, userdata.set_skill_level, skill_id(db, "kubernetes"), None)
    assert claim(db, "kubernetes") is None


def test_level_change_keeps_the_claim(db):
    docker = write(db, userdata.add_profile_skill, "Docker", "proficient", T1)
    with db.begin() as conn:
        conn.execute(update(claims).values(level_origin="model"))
    write(db, userdata.set_skill_level, docker, "expert", T2)
    c = claim(db, "docker")
    assert (c.level, c.level_origin, c.created_at, c.updated_at) == ("expert", "user", T1, T2)
    with pytest.raises(UserDataError):
        write(db, userdata.set_skill_level, docker, "guru")


def test_rename_skill(db):
    docker = write(db, userdata.add_profile_skill, "Docker", "proficient")
    write(db, userdata.add_profile_skill, "Podman", "familiar")
    write(db, userdata.rename_skill, docker, "Docker Engine")
    assert rows(db, skills)[0].name == "Docker Engine"
    assert userdata.identity_claim("docker") in rejected(db)
    with pytest.raises(UserDataError):
        write(db, userdata.rename_skill, docker, "podman")


# --- Grounds and highlights (3.4) ---


def test_a_claim_grounded_by_two_records(db):
    parking = record(db, "city-parking")
    tracker = record(db, "price_tracker", organisation="Example Labs")
    flask = write(db, userdata.add_profile_skill, "Flask", "proficient")
    write(db, userdata.add_ground, flask, parking, "Flask", T1)
    write(db, userdata.add_ground, flask, tracker, None, T2)
    grounds = page_claim(db, "flask")["grounds"]
    assert [(g["record_id"], g["record_label"], g["quote"]) for g in grounds] == [
        (parking, "city-parking", "Flask"),
        (
            tracker,
            "price_tracker — Example Labs",
            "price_tracker, Example Labs",
        ),  # a hand-made ground quotes the record
    ]
    with pytest.raises(UserDataError):
        write(db, userdata.add_ground, flask, parking)
    write(db, userdata.remove_ground, flask, parking)
    assert grounds_of(db, "flask") == [tracker]


def test_ground_needs_a_claim(db):
    parking = record(db, "city-parking")
    write(db, userdata.add_skill_mark, JOB, "Flask", "Flask")
    with pytest.raises(UserDataError, match="profile first"):
        write(db, userdata.add_ground, skill_id(db, "flask"), parking)


def test_ungrounded_claim(db):
    write(db, userdata.add_profile_skill, "Leadership", "proficient")
    c = page_claim(db, "leadership")
    assert c["ungrounded"] is True
    with db.connect() as conn:
        assert queries.profile(conn)["counts"]["ungrounded"] == 1


def test_missing_is_never_ungrounded(db):
    write(db, userdata.add_profile_skill, "AWS", "missing")
    assert page_claim(db, "aws")["ungrounded"] is False


def test_a_highlight_covering_three_claims(db):
    text = "8+ years experience with Python (incl. NumPy, matplotlib, scikit-learn)"
    highlight = write(db, userdata.add_highlight, text)
    for name in ("Python", "NumPy", "scikit-learn"):
        write(db, userdata.add_coverage, highlight, write(db, userdata.add_profile_skill, name, "proficient"), name)
    for key in ("python", "numpy", "scikit-learn"):
        assert [h["text"] for h in page_claim(db, key)["highlights"]] == [text]
    with pytest.raises(UserDataError):
        write(db, userdata.add_coverage, highlight, skill_id(db, "numpy"))


def test_claim_without_a_highlight(db):
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    assert page_claim(db, "docker")["no_highlight"] is True


def test_highlight_edit_and_delete(db):
    highlight = write(db, userdata.add_highlight, "Familiar with CI/CD")
    cicd = write(db, userdata.add_profile_skill, "CI/CD", "familiar")
    write(db, userdata.add_coverage, highlight, cicd, "CI/CD")
    with db.begin() as conn:
        conn.execute(update(highlight_claims).values(origin="suggestion"))
    write(db, userdata.update_highlight, highlight, "Familiar with serverless CI/CD")
    assert userdata.identity_highlight("Familiar with CI/CD") in rejected(db)
    write(db, userdata.remove_coverage, highlight, cicd)
    write(db, userdata.add_coverage, highlight, cicd)
    write(db, userdata.delete_highlight, highlight)
    assert rows(db, highlight_claims) == [] and claim(db, "ci/cd") is not None


@pytest.fixture
def ready(db):
    """A chat model is chosen and the profile has a skill, so link judging can be queued; the queue is empty."""
    write(db, userdata.set_setting, "llm.model", "gemma4:12b")
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    clear_queue(db)
    return db


def clear_queue(engine):
    with engine.begin() as conn:
        conn.execute(update(llm_jobs).where(llm_jobs.c.status == "queued").values(status="done", finished_at=T1))


def queued_links(engine):
    return [j for j in rows(engine, llm_jobs) if j.kind == "links" and j.status == "queued"]


def test_each_change_to_claims_queues_one_links_job(ready):
    parking = record(ready, "city-parking")
    docker = skill_id(ready, "docker")
    highlight = write(ready, userdata.add_highlight, "Docker for everything")
    clear_queue(ready)
    actions = [
        lambda: write(ready, userdata.add_ground, docker, parking),
        lambda: write(ready, userdata.remove_ground, docker, parking),
        lambda: write(ready, userdata.add_coverage, highlight, docker, "Docker"),
        lambda: write(ready, userdata.remove_coverage, highlight, docker),
        lambda: write(ready, userdata.add_profile_skill, "Podman", "familiar"),
        lambda: write(ready, userdata.merge_skill, skill_id(ready, "podman"), docker),
        lambda: write(ready, userdata.remove_alias, "podman"),
    ]
    for action in actions:
        action()
        assert len(queued_links(ready)) == 1
        clear_queue(ready)
    write(ready, userdata.add_line, parking, "no claims change")
    write(ready, userdata.update_highlight, highlight, "Docker for most things")
    assert queued_links(ready) == []


# --- Aliases (3.5) ---


def test_merging_a_near_duplicate(db):
    tracker, parking = record(db, "price_tracker"), record(db, "city-parking")
    postgres = write(db, userdata.add_profile_skill, "Postgres", "familiar")
    write(db, userdata.add_ground, postgres, tracker, "Postgres", T1)
    postgresql = write(db, userdata.add_profile_skill, "PostgreSQL", "proficient")
    write(db, userdata.add_ground, postgresql, parking, "PostgreSQL", T2)
    write(db, userdata.merge_skill, postgres, postgresql)

    assert claim(db, "postgresql").level == "proficient"
    assert grounds_of(db, "postgresql") == sorted([tracker, parking])
    moved = next(g for g in rows(db, claim_records) if g.record_id == tracker)
    assert (moved.quote, moved.created_at) == ("Postgres", T1)  # the ground moves as it was
    assert claim(db, "postgres") is None
    assert page_claim(db, "postgresql")["aliases"] == [{"key": "postgres", "name": "Postgres"}]


def test_level_set_on_an_alias(db):
    write(db, userdata.add_skill_mark, JOB, "Postgres", "Postgres")
    postgres = skill_id(db, "postgres")
    postgresql = write(db, userdata.add_profile_skill, "PostgreSQL", "proficient")
    write(db, userdata.merge_skill, postgres, postgresql)
    write(db, userdata.set_skill_level, postgres, "expert")
    assert claim(db, "postgresql").level == "expert" and claim(db, "postgres") is None
    assert write(db, userdata.add_profile_skill, "postgres", "familiar") == postgresql
    assert claim(db, "postgresql").level == "familiar" and claim(db, "postgres") is None


def test_level_of_an_alias(db):
    write(db, userdata.add_skill_mark, JOB, "Postgres", "Postgres")
    postgresql = write(db, userdata.add_profile_skill, "PostgreSQL", "proficient")
    write(db, userdata.merge_skill, skill_id(db, "postgres"), postgresql)
    with db.connect() as conn:
        [mark] = queries.posting_detail(conn, JOB)["marks"]
        overview = {s["name"]: s for s in queries.skills_overview(conn)}
    assert mark["level"] == "proficient"
    assert (overview["Postgres"]["level"], overview["Postgres"]["in_profile"], overview["Postgres"]["alias_of"]) == (
        "proficient", False, "PostgreSQL",
    )


def test_posting_marks_stay_as_they_are(db):
    for job in (JOB, OTHER):
        write(db, userdata.add_skill_mark, job, "Postgres", "Postgres")
    postgres = skill_id(db, "postgres")
    write(db, userdata.merge_skill, postgres, write(db, userdata.add_profile_skill, "PostgreSQL", "proficient"))
    assert {m.skill_id for m in rows(db, posting_skill_marks)} == {postgres}


def test_alias_of_an_alias_and_overrides_follow(db):
    pg = write(db, userdata.add_profile_skill, "PG", "familiar")
    postgres = write(db, userdata.add_profile_skill, "Postgres", "familiar")
    postgresql = write(db, userdata.add_profile_skill, "PostgreSQL", "proficient")
    write(db, userdata.set_link_override, "psql", postgres, "same")
    write(db, userdata.merge_skill, pg, postgres)
    write(db, userdata.merge_skill, postgres, postgresql)
    assert {a.alias_key: a.skill_id for a in rows(db, skill_aliases)} == {"pg": postgresql, "postgres": postgresql}
    assert rows(db, skill_link_overrides)[0].skill_id == postgresql
    with db.connect() as conn:
        assert queries.resolve_skill(conn, "pg").id == postgresql


def test_merge_refused_without_a_kept_claim_or_into_itself(db):
    write(db, userdata.add_skill_mark, JOB, "Postgres", "Postgres")
    postgres = skill_id(db, "postgres")
    docker = write(db, userdata.add_profile_skill, "Docker", "proficient")
    with pytest.raises(UserDataError, match="add Postgres to the profile"):
        write(db, userdata.merge_skill, docker, postgres)
    with pytest.raises(UserDataError, match="itself"):
        write(db, userdata.merge_skill, docker, docker)


def test_merge_forgets_the_merged_rejection_and_removing_an_alias_keeps_no_claim(db):
    postgres = write(db, userdata.add_profile_skill, "Postgres", "familiar")
    write(db, userdata.remove_profile_skill, postgres)
    assert userdata.identity_claim("postgres") in rejected(db)
    postgresql = write(db, userdata.add_profile_skill, "PostgreSQL", "proficient")
    write(db, userdata.merge_skill, postgres, postgresql)
    assert userdata.identity_claim("postgres") not in rejected(db)
    write(db, userdata.remove_alias, "postgres")
    assert rows(db, skill_aliases) == [] and claim(db, "postgres") is None


# --- Profile details (3.6) ---


def test_headline_and_contact_details(db):
    write(db, userdata.add_detail, "contact", "jane@example.com", "Email")
    write(db, userdata.add_detail, "headline", "PhD Computer Science")
    name = write(db, userdata.add_detail, "name", "Jane Doe")
    with db.connect() as conn:
        details = queries.profile(conn)["details"]
    assert [(d["kind"], d["label"], d["text"]) for d in details] == [
        ("name", None, "Jane Doe"),
        ("headline", None, "PhD Computer Science"),
        ("contact", "Email", "jane@example.com"),
    ]
    write(db, userdata.update_detail, name, "name", "Jane Q. Doe")
    write(db, userdata.delete_detail, details[2]["id"])
    with db.connect() as conn:
        assert [d["text"] for d in queries.profile(conn)["details"]] == ["Jane Q. Doe", "PhD Computer Science"]
    with pytest.raises(UserDataError):
        write(db, userdata.add_detail, "hobby", "chess")


# --- Remembered rejections (3.7) ---


def test_deletions_and_identity_edits_are_remembered(db):
    parking = record(db, "city-parking")
    line = write(db, userdata.add_line, parking, "Flask app")
    write(db, userdata.update_line, line, "A Flask app")
    write(db, userdata.update_record, parking, {"kind": "project", "title": "city-parking", "location": "Example City"})
    old = userdata.identity_record("project", "city-parking", None, None, None)
    assert rejected(db) == {userdata.identity_line(old, "Flask app")}  # a location isn't part of the identity
    write(db, userdata.update_record, parking, {"kind": "project", "title": "city-parking v2"})
    assert old in rejected(db)
    labels = [r.label for r in rows(db, profile_rejections)]
    assert labels == ["Flask app (edited)", "city-parking (edited)"]


def test_forgetting_a_rejection(db):
    chain = write(db, userdata.add_profile_skill, "Chain", "familiar")
    write(db, userdata.remove_profile_skill, chain)
    [r] = rows(db, profile_rejections)
    write(db, userdata.forget_rejection, r.id)
    assert rows(db, profile_rejections) == [] and claim(db, "chain") is None


def test_adding_by_hand_forgets(db):
    jupyter = write(db, userdata.add_profile_skill, "Jupyter", "proficient")
    write(db, userdata.remove_profile_skill, jupyter)
    write(db, userdata.add_profile_skill, "Jupyter", "familiar")
    assert claim(db, "jupyter").level == "familiar" and rows(db, profile_rejections) == []
    parking = record(db, "city-parking")
    write(db, userdata.delete_record, parking)
    record(db, "City-Parking")
    assert rows(db, profile_rejections) == []


# --- The read model (4.1) ---


def test_viewing_the_profile(db):
    for n in range(7):
        record(db, f"project {n}")
    for year in range(2016, 2026):
        record(db, "COMP 1010", "course", "Example University", f"{year}-09", f"{year}-12")
    parking = rows(db, records)[0].id
    for n in range(12):
        sid = write(db, userdata.add_profile_skill, f"skill {n}", "proficient" if n % 2 else "expert")
        if n >= 3:
            write(db, userdata.add_ground, sid, parking)
    write(db, userdata.add_highlight, "a highlight")
    with db.connect() as conn:
        p = queries.profile(conn)
    assert [(kind, len(group)) for kind, group in p["records"]] == [("course", 10), ("project", 7)]
    assert [(level, len(group)) for level, group in p["claims"]] == [("expert", 6), ("proficient", 6)]
    assert p["counts"] == {"records": 17, "by_kind": {"course": 10, "project": 7}, "claims": 12, "ungrounded": 3,
                           "no_highlight": 12, "highlights": 1}
    assert len(p["record_choices"]) == 17 and len(p["claim_choices"]) == 12


def test_stale_override_count(db):
    docker = write(db, userdata.add_profile_skill, "Docker", "proficient")
    podman = write(db, userdata.add_profile_skill, "Podman", "proficient")
    write(db, userdata.set_link_override, "containers", docker, "general")
    write(db, userdata.set_link_override, "oci", podman, "related")
    write(db, userdata.set_link_override, "excel", None)
    write(db, userdata.remove_profile_skill, podman)
    with db.connect() as conn:
        assert queries.stale_override_count(conn) == 1


def test_reset_knowledge_base(db):
    parking = record(db, "city-parking")
    best = record(db, "Best Design", "award")
    write(db, userdata.set_part_of, best, parking)
    write(db, userdata.add_line, parking, "a line")
    write(db, userdata.add_source, parking, "https://example.org")
    python = write(db, userdata.add_profile_skill, "Python", "proficient")
    write(db, userdata.add_ground, python, parking)
    highlight = write(db, userdata.add_highlight, "8+ years with Python")
    write(db, userdata.add_coverage, highlight, python)
    write(db, userdata.add_detail, "name", "Jane Doe")
    pg = write(db, userdata.add_profile_skill, "PostgreSQL", "proficient")
    write(db, userdata.add_skill_mark, JOB, "Postgres", "Postgres")
    write(db, userdata.merge_skill, skill_id(db, "postgres"), pg)
    write(db, userdata.add_profile_skill, "Chain", "familiar")
    write(db, userdata.remove_profile_skill, skill_id(db, "chain"))
    write(db, userdata.set_link_override, "py", python, "same")

    assert write(db, userdata.reset_knowledge_base) == {"records": 2, "claims": 2, "highlights": 1}
    for table in (records, record_lines, record_sources, claims, claim_records, highlight_claims):
        assert rows(db, table) == []
    with db.connect() as conn:
        p = queries.profile(conn)
    assert [d["text"] for d in p["details"]] == ["Jane Doe"] and p["highlights"] == []
    assert len(rows(db, skill_aliases)) == 1 and rejected(db) == {userdata.identity_claim("chain")}
    assert rows(db, skill_link_overrides)[0].skill_id == python
