from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobhunt import userdata
from jobhunt.db import (
    claims,
    dismiss_reasons,
    posting_dismissal_reasons,
    posting_dismissals,
    posting_skill_marks,
    posting_tags,
    posting_triage,
    skills,
    tags,
)
from jobhunt.userdata import UserDataError, name_key

from .conftest import add_posting

JOB = 1  # keys in the order the db fixture imports them
OTHER = 2
T1 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
T3 = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


@pytest.fixture
def db(engine):
    assert add_posting(engine) == JOB
    assert add_posting(engine, "senior-ai-engineer.json") == OTHER
    return engine


def write(engine, fn, *args, **kwargs):
    with engine.begin() as conn:
        return fn(conn, *args, **kwargs)


def all_rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table)).all()


def count(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def reason_id(engine, key):
    with engine.connect() as conn:
        return conn.execute(select(dismiss_reasons.c.id).where(dismiss_reasons.c.key == key)).scalar_one()


# --- Name keys (4.2) ---


def test_name_key():
    assert name_key("  Machine   Learning ") == "machine learning"
    assert name_key("ÉCOLE") == name_key("école")
    assert name_key("Straße") == name_key("STRASSE")


# --- Profile identities (design D6) ---


def test_identities_ignore_case_and_whitespace():
    a = userdata.identity_record("degree", "PhD  Computer Science", "Example University", None, "2022")
    b = userdata.identity_record("degree", " phd computer science", "EXAMPLE   university ", None, "2022")
    assert a == b
    assert userdata.identity_line(a, "Thesis:  Evolutionary search") == userdata.identity_line(
        b, "thesis: evolutionary SEARCH"
    )
    assert userdata.identity_highlight("8+ years  with Python") == userdata.identity_highlight("8+ YEARS with python ")
    assert userdata.identity_source(a, "https://GitHub.com/x") == userdata.identity_source(b, " https://github.com/x")


def test_identities_differ_by_kind_dates_and_document():
    phd = userdata.identity_record("degree", "PhD", "Dal", None, "2022")
    assert phd != userdata.identity_record("other", "PhD", "Dal", None, "2022")
    assert phd != userdata.identity_record("degree", "PhD", "Dal", "2018", "2022")
    assert userdata.identity_source(phd, document_id=3) != userdata.identity_source(phd, document_id=4)


def test_child_identities_change_with_the_record_title():
    old = userdata.identity_record("project", "city-parking", None, None, None)
    new = userdata.identity_record("project", "city-parking v2", None, None, None)
    claim = userdata.identity_claim("flask")
    assert userdata.identity_line(old, "Flask") != userdata.identity_line(new, "Flask")
    assert userdata.identity_source(old, "https://github.com/x") != userdata.identity_source(new, "https://github.com/x")
    assert userdata.identity_ground(claim, old) != userdata.identity_ground(claim, new)
    assert userdata.identity_part_of(old, new) != userdata.identity_part_of(new, old)


def test_tag_reuses_key(db):
    first = write(db, userdata.get_or_create_tag, "ml")
    second = write(db, userdata.get_or_create_tag, " ML ")
    assert first.id == second.id and second.name == "ml"
    assert count(db, tags) == 1


def test_different_case_never_duplicates(db):
    write(db, userdata.get_or_create_skill, "PyTorch")
    write(db, userdata.get_or_create_skill, "pytorch")
    write(db, userdata.get_or_create_skill, "PYTORCH ")
    assert [s.name for s in all_rows(db, skills)] == ["PyTorch"]


def test_empty_name_rejected(db):
    with pytest.raises(UserDataError):
        write(db, userdata.get_or_create_tag, "   ")


# --- Ratings, notes, tags (4.3) ---


def test_rating_a_posting(db):
    write(db, userdata.set_rating, JOB, "interest", 4)
    row = all_rows(db, posting_triage)[0]
    assert (row.interest, row.fit) == (4, None)


def test_clearing_a_rating(db):
    write(db, userdata.set_rating, JOB, "interest", 4)
    write(db, userdata.set_rating, JOB, "fit", 2)
    write(db, userdata.set_rating, JOB, "interest", None)
    row = all_rows(db, posting_triage)[0]
    assert (row.interest, row.fit) == (None, 2)


@pytest.mark.parametrize("value", [0, 6, "3", 2.5])
def test_rating_out_of_range(db, value):
    with pytest.raises(UserDataError):
        write(db, userdata.set_rating, JOB, "interest", value)
    assert count(db, posting_triage) == 0


def test_notes_keep_ratings(db):
    write(db, userdata.set_rating, JOB, "interest", 5)
    write(db, userdata.set_notes, JOB, "**Ask** about visa")
    row = all_rows(db, posting_triage)[0]
    assert row.interest == 5 and row.notes == "**Ask** about visa"
    write(db, userdata.set_notes, JOB, "   ")
    assert all_rows(db, posting_triage)[0].notes is None


def test_tag_reuse_across_postings(db):
    write(db, userdata.add_tag, JOB, "ml")
    write(db, userdata.add_tag, OTHER, " ML ")
    assert count(db, tags) == 1
    assert {r.job_id for r in all_rows(db, posting_tags)} == {JOB, OTHER}


def test_no_duplicate_tag_on_posting(db):
    write(db, userdata.add_tag, JOB, "ml")
    tag = write(db, userdata.add_tag, JOB, "ML")
    assert count(db, posting_tags) == 1
    write(db, userdata.remove_tag, JOB, tag.id)
    assert count(db, posting_tags) == 0
    assert count(db, tags) == 1  # the tag itself stays for suggestions


# --- Dismissals (4.4) ---


def test_dismiss_with_reasons(db):
    reasons = [reason_id(db, "too senior"), reason_id(db, "location or on-site")]
    write(db, userdata.dismiss, JOB, reasons, " far away ", now=T1)
    dismissal = all_rows(db, posting_dismissals)[0]
    assert dismissal.comment == "far away" and dismissal.restored_at is None
    assert {r.reason_id for r in all_rows(db, posting_dismissal_reasons)} == set(reasons)


def test_dismiss_needs_a_reason(db):
    with pytest.raises(UserDataError):
        write(db, userdata.dismiss, JOB, [])


def test_at_most_one_open_dismissal(db):
    write(db, userdata.dismiss, JOB, [reason_id(db, "other")])
    with pytest.raises(UserDataError):
        write(db, userdata.dismiss, JOB, [reason_id(db, "company")])
    assert count(db, posting_dismissals) == 1


def test_restore_and_dismiss_again_keeps_history(db):
    write(db, userdata.dismiss, JOB, [reason_id(db, "too senior"), reason_id(db, "location or on-site")], now=T1)
    write(db, userdata.restore, JOB, now=T2)
    with db.connect() as conn:
        assert userdata.open_dismissal(conn, JOB) is None
    write(db, userdata.dismiss, JOB, [reason_id(db, "compensation")], now=T3)

    first, second = sorted(all_rows(db, posting_dismissals), key=lambda r: r.id)
    assert (first.dismissed_at, first.restored_at) == (T1, T2)
    assert (second.dismissed_at, second.restored_at) == (T3, None)
    assert count(db, posting_dismissal_reasons) == 3


def test_restore_when_not_dismissed(db):
    with pytest.raises(UserDataError):
        write(db, userdata.restore, JOB)


def test_custom_reason(db):
    added = write(db, userdata.add_dismiss_reason, "Contract only")
    assert added.position == 9 and added.key == "contract only"
    again = write(db, userdata.add_dismiss_reason, "contract ONLY")
    assert again.id == added.id and count(db, dismiss_reasons) == 9


# --- Skill marks and levels (4.5) ---


def test_marking_a_skill(db):
    mark_id = write(db, userdata.add_skill_mark, JOB, " PyTorch ", "Design  AI-driven\n automation", now=T1)
    mark = all_rows(db, posting_skill_marks)[0]
    assert mark.id == mark_id and mark.quote == "Design AI-driven automation"
    assert [s.name for s in all_rows(db, skills)] == ["PyTorch"]
    with db.connect() as conn:
        from jobhunt.store import latest_snapshot

        assert mark.snapshot_id == latest_snapshot(conn, JOB).id
    write(db, userdata.remove_skill_mark, mark_id)
    assert count(db, posting_skill_marks) == 0


def test_quote_found_ignores_case_and_markup():
    html = "<p>Experience with <strong>PyTorch</strong>\n and   SQL</p><ul><li>one</li><li>two</li></ul>"
    assert userdata.quote_found("experience with pytorch and sql", html)
    assert userdata.quote_found("one two", html)
    assert not userdata.quote_found("TensorFlow", html)


def test_description_changed_mark_not_found(db):
    write(db, userdata.add_skill_mark, JOB, "Data lineage", "AI-driven automation data lineage")
    add_posting(
        db,
        tag="v2",
        captured_at=T2,
        description_html="<p>Rewritten posting.</p>",
        description_text="Rewritten posting.",
    )
    mark = all_rows(db, posting_skill_marks)[0]
    with db.connect() as conn:
        from jobhunt.store import latest_snapshot

        latest = latest_snapshot(conn, JOB)
    assert latest.id != mark.snapshot_id
    assert not userdata.quote_found(mark.quote, latest.description_html)


def test_level_belongs_to_skill(db):
    write(db, userdata.add_skill_mark, JOB, "Kubernetes", "Design")
    write(db, userdata.add_skill_mark, OTHER, "kubernetes", "Design")
    skill = all_rows(db, skills)[0]
    write(db, userdata.set_skill_level, skill.id, "missing")
    assert count(db, skills) == 1
    assert [(c.skill_id, c.level) for c in all_rows(db, claims)] == [(skill.id, "missing")]  # the skill's claim
    write(db, userdata.set_skill_level, skill.id, None)
    assert all_rows(db, claims) == []
    with pytest.raises(UserDataError):
        write(db, userdata.set_skill_level, skill.id, "have")
