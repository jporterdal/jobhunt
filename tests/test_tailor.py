"""Tailoring a CV: the choice parser, non-disclosure, the greedy highlight cover, record selection, details and
gaps (`cv-rank@1`)."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from werkzeug.datastructures import MultiDict

from jobhunt import tailor, userdata
from jobhunt.db import DERIVED_TABLES, OPERATIONAL_TABLES, USER_TABLES, captures, posting_snapshots, postings
from jobhunt.tailor import Choice

from .conftest import add_posting
from .test_userdata import write

BANK, EMPTY = 1, 2  # keys in the order the db fixture imports them
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(engine):
    assert add_posting(engine, "data-automation.json") == BANK
    assert add_posting(engine, "senior-ai-engineer.json") == EMPTY
    return engine


def mark(engine, name, importance="required", job=BANK):
    return write(engine, userdata.add_skill_mark, job, name, "Design", importance=importance)


def skill(engine, name, level="proficient"):
    return write(engine, userdata.add_profile_skill, name, level)


def highlight(engine, text, *skill_ids):
    highlight_id = write(engine, userdata.add_highlight, text)
    for skill_id in skill_ids:
        write(engine, userdata.add_coverage, highlight_id, skill_id)
    return highlight_id


def record(engine, kind, title, *grounds, **fields):
    record_id = write(engine, userdata.add_record, {"kind": kind, "title": title, **fields})
    for skill_id in grounds:
        write(engine, userdata.add_ground, skill_id, record_id)
    return record_id


def propose(engine, job=BANK, **args):
    params = MultiDict()
    for name, value in args.items():
        for v in value if isinstance(value, (list, tuple)) else [value]:
            params.add(name, str(v))
    with engine.connect() as conn:
        return tailor.propose(conn, job, Choice.from_args(params), NOW)


def chosen_highlights(p):
    return [h["text"] for h in sorted((h for h in p.highlights if h["chosen"]), key=lambda h: h["position"])]


def chosen_records(p, kind):
    return [r["label"] for g in p.records if g["kind"] == kind for r in g["records"] if r["chosen"]]


def listed_records(p):
    return {r["id"] for g in p.records for r in g["records"]}


def gain_of(p, text):
    return next(h["gain"] for h in p.highlights if h["text"] == text)


def counts(engine):
    with engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in USER_TABLES + DERIVED_TABLES + OPERATIONAL_TABLES + (postings, captures, posting_snapshots)}


# --- The choice (5.1) ---


def test_choice_defaults():
    choice = Choice.from_args(MultiDict())
    assert (choice.budget, choice.counts["publication"], choice.counts["project"], choice.tuned) == (9, 3, 0, False)
    assert choice == Choice()


@pytest.mark.parametrize("args", [
    {"budget": "lots", "count_publication": "-1"},
    {"budget": "999", "count_publication": "1e3"},
    {"budget": "", "count_publication": "51"},
])
def test_bad_numbers_fall_back_to_defaults(args):
    choice = Choice.from_args(MultiDict(args))
    assert (choice.budget, choice.counts["publication"]) == (tailor.HIGHLIGHT_BUDGET, 3)


def test_ticks_need_tuned_and_auto_ids_left_unchecked_are_unticked():
    assert Choice.from_args(MultiDict([("h", "4")])).ticked["h"] == frozenset()
    choice = Choice.from_args(MultiDict([("tuned", "1"), ("h", "4"), ("h", "5"), ("a_h", "5"), ("a_h", "6"),
                                         ("x_h", "7"), ("x_h", "4"), ("h", "x")]))
    assert choice.ticked["h"] == {4} and choice.unticked["h"] == {6, 7}
    assert Choice.from_args(MultiDict(choice.to_args())) == choice


def test_ids_that_dont_exist_are_ignored(db):
    python = skill(db, "Python")
    mark(db, "Python")
    highlight(db, "Python daily", python)
    p = propose(db, tuned=1, h=[999], r=[998], d=[997], x_h=[996])
    assert chosen_highlights(p) == ["Python daily"]


# --- Non-disclosure (5.2) ---


def test_private_record_left_out(db):
    django = skill(db, "Django")
    mark(db, "Django")
    secret = record(db, "project", "Secret Shop", django, organisation="Hidden Corp", location="Nowhere")
    write(db, userdata.set_disclosure, secret, "private")
    p = propose(db, count_project=3)
    assert secret not in listed_records(p)
    text = json.dumps(p.content)
    assert "Secret Shop" not in text and "Hidden Corp" not in text and "Nowhere" not in text
    assert [g["name"] for g in p.gaps] == ["Django"]  # a private record shows nothing
    assert secret not in listed_records(propose(db, count_project=3, tuned=1, r=[secret]))


def test_private_through_its_context(db):
    context = record(db, "role", "Undisclosed client work")
    dependent = record(db, "project", "Public-looking project")
    write(db, userdata.set_part_of, dependent, context)
    write(db, userdata.set_disclosure, context, "private")
    p = propose(db, count_project=3)
    assert {context, dependent}.isdisjoint(listed_records(p))


def test_highlight_naming_a_private_record(db):
    python = skill(db, "Python")
    mark(db, "Python")
    secret = record(db, "role", "Consultant", organisation="Acme Secret Labs")
    write(db, userdata.set_disclosure, secret, "private")
    named = highlight(db, "Built search at ACME SECRET LABS in Python and Rust", python)
    highlight(db, "Python every day", python)
    p = propose(db)
    row = next(h for h in p.highlights if h["id"] == named)
    assert row["flag"] == "Consultant — Acme Secret Labs" and not row["chosen"]
    assert chosen_highlights(p) == ["Python every day"]
    assert named in [h["id"] for h in propose(db, tuned=1, h=[named]).highlights if h["chosen"]]


def test_private_source_address_and_short_organisation():
    records = [{"title": None, "organisation": "IBM", "label": "x",
                "sources": [{"url": "https://www.secret.example/repo/"}]}]
    needles = tailor.private_needles(records)
    assert tailor.private_mention("See secret.example/repo for code", needles) == "x"
    assert tailor.private_mention("Worked with IBM mainframes", needles) is None  # under 4 characters


# --- Highlights (5.3) ---


def test_a_posting_skill_counts_once(db):
    python, flask = skill(db, "Python"), skill(db, "Flask")
    mark(db, "Python", "required")
    mark(db, "Flask", "preferred")
    highlight(db, "A: Python", python)
    highlight(db, "B: Python and Flask", python, flask)
    p = propose(db)
    assert chosen_highlights(p) == ["B: Python and Flask"]
    assert gain_of(p, "B: Python and Flask") == pytest.approx(2.55)
    assert gain_of(p, "A: Python") == pytest.approx(0)


def test_covering_what_the_posting_doesnt_ask_for(db):
    python, java, cpp = skill(db, "Python"), skill(db, "Java"), skill(db, "C++")
    mark(db, "Python", "required")
    highlight(db, "C: Python, Java and C++", python, java, cpp)
    highlight(db, "A: Python", python)
    with db.connect() as conn:
        p = tailor.propose(conn, BANK, Choice(budget=0), NOW)  # nothing chosen: every gain against nothing shown
    assert gain_of(p, "A: Python") == pytest.approx(1.7)
    assert gain_of(p, "C: Python, Java and C++") == pytest.approx(1.5)
    assert chosen_highlights(propose(db))[0] == "A: Python"


def test_budget(db):
    for n in range(12):
        sid = skill(db, f"Skill {n}")
        mark(db, f"Skill {n}")
        highlight(db, f"Highlight {n}", sid)
    assert len(chosen_highlights(propose(db))) == 9
    assert len(chosen_highlights(propose(db, budget=4))) == 4


def test_missing_skills_show_nothing(db):
    kubernetes = skill(db, "Kubernetes", "missing")
    mark(db, "Kubernetes")
    highlight(db, "Kubernetes clusters", kubernetes)
    p = propose(db)
    assert chosen_highlights(p) == [] and gain_of(p, "Kubernetes clusters") <= 0


def test_unticking_the_top_highlight(db):
    top = None
    for n in range(12):
        sid = skill(db, f"Skill {n}")
        mark(db, f"Skill {n}", "required" if n == 0 else "preferred")
        hid = highlight(db, f"Highlight {n}", sid)
        top = top or hid
    p = propose(db)
    assert chosen_highlights(p)[0] == "Highlight 0"
    p = propose(db, tuned=1, a_h=[top])  # the form: Highlight 0 was chosen by the ranking, and is now unchecked
    assert "Highlight 0" not in chosen_highlights(p) and len(chosen_highlights(p)) == 9
    assert next(h for h in p.highlights if h["id"] == top)["unticked"]


def test_hand_ticked_highlight_goes_after_the_chosen(db):
    python, java = skill(db, "Python"), skill(db, "Java")
    mark(db, "Python")
    extra = highlight(db, "Java on the side", java)
    highlight(db, "Python", python)
    assert chosen_highlights(propose(db, tuned=1, h=[extra])) == ["Python", "Java on the side"]


def test_alias_linked_posting_skill_counts(db):
    python = skill(db, "Python")
    py = skill(db, "Py", "learning")
    write(db, userdata.merge_skill, py, python)
    mark(db, "Py")
    highlight(db, "Python daily", python)
    p = propose(db)
    assert chosen_highlights(p) == ["Python daily"]
    assert gain_of(p, "Python daily") == pytest.approx(1.7)


# --- Records (5.4) ---


def test_a_relevant_publication_comes_first(db):
    es = skill(db, "Evolution strategies")
    mark(db, "Evolution strategies")
    record(db, "publication", "Older paper", es, end_date="2019")
    record(db, "publication", "Newest paper", end_date="2025")
    assert chosen_records(propose(db, count_publication=1), "publication") == ["Older paper (2019)"]


def test_filling_with_the_newest(db):
    es = skill(db, "Evolution strategies")
    mark(db, "Evolution strategies")
    record(db, "publication", "Relevant", es, end_date="2015")
    for year in (2018, 2020, 2022):
        record(db, "publication", f"Paper {year}", end_date=str(year))
    p = propose(db)
    assert chosen_records(p, "publication") == ["Paper 2022 (2022)", "Paper 2020 (2020)", "Relevant (2015)"]
    titles = [i["payload"]["title"] for i in p.content["items"] if i["section"] == "publication"]
    assert titles == ["Paper 2022", "Paper 2020", "Relevant"]  # printed newest first
    assert p.content["left_out"] == ["publication"]


def test_projects_by_default(db):
    ids = {kind: record(db, kind, f"A {kind}") for kind in ("role", "course", "degree", "award", "project")}
    p = propose(db)
    assert chosen_records(p, "project") == []
    for kind in ("role", "course", "degree", "award"):
        assert chosen_records(p, kind) == [f"A {kind}"]
    assert ids["project"] in listed_records(p)


def test_raising_a_count(db):
    django, sql = skill(db, "Django"), skill(db, "SQL")
    mark(db, "Django")
    mark(db, "SQL", "preferred")
    record(db, "project", "Both", django, sql, end_date="2019")
    record(db, "project", "Django only", django, end_date="2020")
    record(db, "project", "Neither", end_date="2026")
    assert chosen_records(propose(db, count_project=2), "project") == ["Django only (2020)", "Both (2019)"]


def test_unticked_record_and_ticked_past_the_count(db):
    role = record(db, "role", "Professor")
    project = record(db, "project", "tidyplots")
    p = propose(db, tuned=1, a_r=[role], r=[project])
    assert chosen_records(p, "role") == [] and chosen_records(p, "project") == ["tidyplots"]


def test_condensed_courses_and_nesting(db):
    for start, end in (("2024-01", "2024-04"), ("2026-09", "2026-12"), ("2025-01", "2025-04")):
        record(db, "course", "COMP 1000", organisation="Example Polytechnic", start_date=start, end_date=end)
    phd = record(db, "degree", "PhD", end_date="2022")
    thesis = record(db, "publication", "Thesis", end_date="2022")
    write(db, userdata.set_part_of, thesis, phd)
    paper = record(db, "publication", "EXCONF 2024 paper", end_date="2024")
    tidyplots = record(db, "project", "tidyplots")
    write(db, userdata.set_part_of, tidyplots, paper)

    p = propose(db, count_publication=1, tuned=1, r=[tidyplots], x_r=[paper])
    sections = [(i["section"], i["source_kind"]) for i in p.content["items"]]
    assert sections == [("course", "course_group"), ("degree", "record"), ("project", "record")]
    course = p.content["items"][0]["payload"]
    assert len(course["terms"]) == 3 and len(course["record_ids"]) == 3
    degree = p.content["items"][1]["payload"]
    assert [c["title"] for c in degree["children"]] == ["Thesis"]
    assert p.content["items"][2]["payload"]["context"] == {"title": "EXCONF 2024 paper", "organisation": None}
    assert next(r for g in p.records for r in g["records"] if r["id"] == thesis)["under"] == "PhD (2022)"


# --- Details, gaps, the proposal (5.5) ---


def test_default_details(db):
    ids = {
        "name": write(db, userdata.add_detail, "name", "Ada"),
        "contact1": write(db, userdata.add_detail, "contact", "Example City"),
        "contact2": write(db, userdata.add_detail, "contact", "ada@example.com", "Email"),
        "goal": write(db, userdata.add_detail, "goal", "To build"),
        "summary1": write(db, userdata.add_detail, "summary", "One"),
        "summary2": write(db, userdata.add_detail, "summary", "Two"),
    }
    p = propose(db)
    chosen = {d["id"] for d in p.details if d["chosen"]}
    assert chosen == {ids["name"], ids["contact1"], ids["contact2"], ids["goal"]}
    assert [i["section"] for i in p.content["items"]] == ["header", "header", "header", "goal"]
    p = propose(db, tuned=1, d=[ids["summary2"]])
    assert ids["summary2"] in {d["id"] for d in p.details if d["chosen"]}


def test_a_skill_no_highlight_shows(db):
    skill(db, "PostgreSQL", "familiar")
    mark(db, "PostgreSQL", "required")
    [gap] = propose(db).gaps
    assert (gap["name"], gap["importance"], gap["skill_name"], gap["covered_by_unchosen"]) == (
        "PostgreSQL", "required", "PostgreSQL", False)


def test_gap_covered_by_an_unchosen_highlight(db):
    sql = skill(db, "PostgreSQL", "familiar")
    mark(db, "PostgreSQL", "preferred")
    mark(db, "Kotlin", "required")
    hid = highlight(db, "PostgreSQL tuning", sql)
    [gap] = propose(db, tuned=1, a_h=[hid]).gaps
    assert gap["covered_by_unchosen"] is True


def test_shown_by_a_record(db):
    django = skill(db, "Django")
    mark(db, "Django")
    project = record(db, "project", "Shop", django)
    assert [g["name"] for g in propose(db).gaps] == ["Django"]
    assert propose(db, tuned=1, r=[project]).gaps == []  # ticking a project closes the gaps its grounds cover


def test_skill_the_user_lacks(db):
    skill(db, "Kubernetes", "missing")
    mark(db, "Kubernetes")
    mark(db, "Terraform")
    assert propose(db).gaps == []


def test_gaps_required_first_then_by_name(db):
    for name, importance in (("Zig", "required"), ("Ada", "preferred"), ("Go", "required")):
        skill(db, name)
        mark(db, name, importance)
    assert [g["name"] for g in propose(db).gaps] == ["Go", "Zig", "Ada"]


def test_posting_without_skills(db):
    python = skill(db, "Python")
    highlight(db, "Python daily", python)
    record(db, "degree", "PhD")
    write(db, userdata.add_detail, "name", "Ada")
    p = propose(db, job=EMPTY)
    assert not p.has_skills and p.score is None
    assert chosen_highlights(p) == [] and chosen_records(p, "degree") == ["PhD"]
    assert [d["chosen"] for d in p.details] == [True]


def test_propose_writes_nothing(db):
    python = skill(db, "Python")
    mark(db, "Python")
    highlight(db, "Python daily", python)
    record(db, "project", "Shop", python)
    before = counts(db)
    p = propose(db, count_project=2)
    assert counts(db) == before
    assert p.score == pytest.approx(0.85) and p.method == "cv-rank@1"
    assert p.content["produced"] == "2026-10-16"
