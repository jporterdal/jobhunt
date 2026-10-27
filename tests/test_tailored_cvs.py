"""Saved CVs: frozen copies of a proposal (userdata), their readers (queries), and that nothing but the user's own
actions on a CV changes them."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from jobhunt import queries, tailor, userdata
from jobhunt.cvdoc import layout
from jobhunt.db import highlights, tailored_cv_items, tailored_cvs

from .conftest import add_posting
from .test_profile import add_document
from .test_profile_suggestions import add_run, rec
from .test_userdata import write

BANK = 1  # the posting the db fixture imports
T1 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(engine):
    assert add_posting(engine) == BANK
    for text, name, importance in (("First Python", "Python", "required"), ("Second Python", "SQL", "preferred"),
                                   ("Third Python", "Go", None)):
        skill_id = write(engine, userdata.add_profile_skill, name, "proficient")
        write(engine, userdata.add_skill_mark, BANK, name, "Design", importance=importance)
        write(engine, userdata.add_coverage, write(engine, userdata.add_highlight, text), skill_id)
    write(engine, userdata.add_detail, "name", "Ada")
    phd = write(engine, userdata.add_record, {"kind": "degree", "title": "PhD", "end_date": "2022"})
    thesis = write(engine, userdata.add_record, {"kind": "publication", "title": "Thesis", "end_date": "2022"})
    write(engine, userdata.set_part_of, thesis, phd)
    write(engine, userdata.add_record, {"kind": "publication", "title": "Unprinted paper", "end_date": "2010"})
    return engine


def save(engine, budget=3, count_publication=1, now=T1):
    with engine.begin() as conn:
        proposal = tailor.propose(conn, BANK, tailor.Choice(budget=budget, counts={**tailor.Choice().counts,
                                                                                  "publication": count_publication}))
        return userdata.save_tailored_cv(conn, BANK, proposal, now)


def saved(engine, cv_id):
    with engine.connect() as conn:
        return queries.tailored_cv(conn, cv_id)


def frozen(engine, cv_id):
    """The CV's stored rows, as they are."""
    with engine.connect() as conn:
        return (conn.execute(select(tailored_cvs).where(tailored_cvs.c.id == cv_id)).one(),
                conn.execute(select(tailored_cv_items).where(tailored_cv_items.c.cv_id == cv_id)
                             .order_by(tailored_cv_items.c.id)).all())


def labels(cv, section=None):
    return [i["label"] for i in cv["items"] if section is None or i["section"] == section]


def item_id(cv, label):
    return next(i["id"] for i in cv["items"] if i["label"] == label)


def test_saving_copies_the_proposal(db):
    cv = saved(db, save(db))
    assert labels(cv) == ["Ada", "First Python", "Second Python", "Third Python", "PhD"]
    assert cv["cv"].method == "cv-rank@1" and cv["cv"].match_score == pytest.approx(
        0.85
    )  # every skill shown at proficient
    assert cv["posting"]["job_id"] == BANK and cv["posting"]["url"] and cv["posting"]["title"]
    phd = next(i for i in cv["items"] if i["label"] == "PhD")
    assert [c["title"] for c in phd["payload"]["children"]] == ["Thesis"]  # the thesis travels under its degree
    built = layout.build(cv["content"])
    assert built.header.produced == "October 2026"
    assert [s.heading for s in built.sections] == ["Skills & Experience", "Education"]
    assert json.loads(cv["cv"].choice_json)["choice"]["budget"] == 3


def test_profile_edited_after_saving(db):
    cv_id = save(db)
    before = frozen(db, cv_id)
    with db.begin() as conn:
        first = conn.execute(select(highlights.c.id).where(highlights.c.text == "First Python")).scalar_one()
        userdata.update_highlight(conn, first, "Rewritten")
        phd = next(r["id"] for _, g in queries.profile(conn)["records"] for r in g if r["title"] == "PhD")
        userdata.delete_record(conn, phd)
    assert frozen(db, cv_id) == before
    cv = saved(db, cv_id)
    assert "First Python" in labels(cv) and "PhD" in labels(cv)
    assert next(i for i in cv["items"] if i["label"] == "PhD")["deleted"]
    assert not next(i for i in cv["items"] if i["label"] == "First Python")["deleted"]  # edited, not deleted


def test_deleted_highlight_is_marked(db):
    cv_id = save(db)
    with db.begin() as conn:
        third = conn.execute(select(highlights.c.id).where(highlights.c.text == "Third Python")).scalar_one()
        userdata.delete_highlight(conn, third)
    marks = {i["label"]: i["deleted"] for i in saved(db, cv_id)["items"]}
    assert marks["Third Python"] and not marks["Second Python"]


def test_record_made_private_after_saving(db):
    cv_id = save(db)
    with db.begin() as conn:
        thesis = next(r["id"] for _, g in queries.profile(conn)["records"] for r in g if r["title"] == "Thesis")
        userdata.set_disclosure(conn, thesis, "private")  # the child of the printed PhD
    cv = saved(db, cv_id)
    assert [i["label"] for i in cv["items"] if i["private_now"]] == ["PhD"]
    assert "PhD" in labels(cv)  # still there until removed


def test_two_cvs_for_one_posting_newest_first(db):
    first, second = save(db, budget=1, now=T1), save(db, budget=2, now=T2)
    with db.connect() as conn:
        listed = queries.tailored_cvs_for_posting(conn, BANK)
    assert [row.id for row in listed] == [second, first]
    assert len(labels(saved(db, first), "highlights")) == 1 and len(labels(saved(db, second), "highlights")) == 2


def test_moving_a_highlight(db):
    cv_id = save(db)
    cv = saved(db, cv_id)
    write(db, userdata.move_cv_item, cv_id, item_id(cv, "Third Python"), "up", T2)
    assert labels(saved(db, cv_id), "highlights") == ["First Python", "Third Python", "Second Python"]
    with db.connect() as conn:
        assert conn.execute(select(highlights.c.text).order_by(highlights.c.id)).scalars().all() == [
            "First Python", "Second Python", "Third Python"]
    before = frozen(db, cv_id)
    write(db, userdata.move_cv_item, cv_id, item_id(cv, "First Python"), "up", T2)  # already first
    write(db, userdata.move_cv_item, cv_id, item_id(cv, "Second Python"), "down", T2)  # already last
    write(db, userdata.move_cv_item, cv_id, item_id(cv, "Ada"), "down", T2)  # alone in the header
    assert frozen(db, cv_id) == before
    assert saved(db, cv_id)["cv"].updated_at == T2


def test_removing_a_parent_removes_its_children(db):
    cv_id = save(db)
    cv = saved(db, cv_id)
    assert layout.build(cv["content"]).sections[-1].heading == "Education"
    write(db, userdata.remove_cv_item, cv_id, item_id(cv, "PhD"), T2)
    cv = saved(db, cv_id)
    assert "PhD" not in labels(cv)
    assert "Thesis" not in json.dumps(cv["content"])
    assert set(cv["content"]["left_out"]) >= {"degree", "publication"}


def test_removing_from_another_cv_is_refused(db):
    first, second = save(db), save(db)
    with pytest.raises(userdata.UserDataError):
        write(db, userdata.remove_cv_item, second, item_id(saved(db, first), "Ada"))


def test_deleting_a_cv(db):
    first, second = save(db), save(db)
    other_before = frozen(db, second)
    with db.connect() as conn:
        profile_before = queries.profile(conn)
    write(db, userdata.delete_tailored_cv, first)
    assert saved(db, first) is None
    with db.connect() as conn:
        assert conn.execute(select(tailored_cv_items).where(tailored_cv_items.c.cv_id == first)).all() == []
        assert queries.profile(conn) == profile_before
    assert frozen(db, second) == other_before


def test_accepting_a_suggestion_and_editing_the_profile_leave_it(db):
    cv_id = save(db)
    before = frozen(db, cv_id)
    add_run(db, add_document(db), records_=[rec("New project")])
    with db.begin() as conn:
        userdata.accept_all_profile_suggestions(conn, "record")
        userdata.add_detail(conn, "goal", "A new goal")
        userdata.add_highlight(conn, "Another highlight")
    assert frozen(db, cv_id) == before
