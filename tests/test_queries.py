from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from jobhunt import queries, userdata
from jobhunt.db import applications, dismiss_reasons
from jobhunt.queries import ListFilters

from .conftest import add_posting

BANK, SIMILAR, AI, ECON = 1, 2, 3, 4  # keys in the order the db fixture imports them
T0 = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 15, 0, tzinfo=UTC)


@pytest.fixture
def db(engine):
    assert add_posting(engine, "data-automation.json", captured_at=at(20)) == BANK  # BANK, On-site
    assert add_posting(engine, "innovation-lab.json", captured_at=at(21)) == SIMILAR  # SIMILAR, Hybrid
    assert add_posting(  # AI, Hybrid
        engine,
        "senior-ai-engineer.json",
        captured_at=at(22),
        description_text="Experience with PyTorch required.",
        description_html="<p>Experience with <strong>PyTorch</strong> required.</p>",
    ) == AI
    assert add_posting(engine, "health-economist.json", captured_at=at(23)) == ECON  # ECON
    return engine


def write(engine, fn, *args, **kwargs):
    with engine.begin() as conn:
        return fn(conn, *args, **kwargs)


def ids(engine, **filters) -> list[str]:
    with engine.connect() as conn:
        return [r["job_id"] for r in queries.posting_list(conn, ListFilters(**filters))]


def reason(engine, key="other"):
    with engine.connect() as conn:
        return conn.execute(select(dismiss_reasons.c.id).where(dismiss_reasons.c.key == key)).scalar_one()


def application(engine, job_id, status):
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            insert(applications).values(
                job_id=job_id, title="t", company="c", status=status, created_at=now, updated_at=now
            )
        )


# --- Posting list (5.1) ---


def test_default_order_newest_seen_first(db):
    assert ids(db) == [ECON, AI, SIMILAR, BANK]


def test_default_hides_dismissed(db):
    write(db, userdata.dismiss, AI, [reason(db)])
    assert ids(db) == [ECON, SIMILAR, BANK]
    assert ids(db, dismissed="only") == [AI]
    assert ids(db, dismissed="included") == [ECON, AI, SIMILAR, BANK]
    write(db, userdata.restore, AI)
    assert ids(db) == [ECON, AI, SIMILAR, BANK]


def test_row_contents(db):
    write(db, userdata.add_tag, BANK, "ml")
    write(db, userdata.set_rating, BANK, "interest", 4)
    application(db, BANK, "applied")
    with db.connect() as conn:
        row = next(r for r in queries.posting_list(conn) if r["job_id"] == BANK)
    assert row["title"] == "Analytics Manager, Reporting Automation (Example City)"
    assert row["company"] == "Example Bank" and row["workplace_type"] == "On-site"
    assert row["url"] == "https://jobs.example.com/view/A-1001"
    assert row["interest"] == 4 and row["application_status"] == "applied"
    assert [t["name"] for t in row["tags"]] == ["ml"]
    assert row["last_seen_at"] == at(20) and row["posted_on_estimate"] is not None


def test_text_search_any_case(db):
    assert ids(db, q="pytorch") == [AI]
    assert ids(db, q="EXAMPLE BANK") == [BANK]
    assert ids(db, q="data automation") == [BANK]


def test_search_escapes_wildcards(db):
    assert ids(db, q="%") == []
    assert ids(db, q="_") == []


def test_search_and_filter_combined(db):
    add_posting(db, "data-automation.json", captured_at=at(24), tag="v2", description_text="We use PyTorch daily.")
    write(db, userdata.set_rating, AI, "interest", 3)
    write(db, userdata.set_rating, BANK, "interest", 2)
    assert set(ids(db, q="pytorch")) == {AI, BANK}
    assert ids(db, q="pytorch", min_interest=3) == [AI]


def test_tag_filter(db):
    write(db, userdata.add_tag, BANK, "ML")
    write(db, userdata.add_tag, AI, "remote-ok")
    assert ids(db, tag=" ml ") == [BANK]


def test_unrated_filter(db):
    write(db, userdata.set_rating, BANK, "interest", 4)
    write(db, userdata.set_rating, AI, "fit", 4)
    assert ids(db, unrated=True) == [ECON, AI, SIMILAR]
    write(db, userdata.set_rating, BANK, "interest", None)
    assert BANK in ids(db, unrated=True)


def test_workplace_filter(db):
    assert ids(db, workplace="Hybrid") == [AI, SIMILAR]
    assert ids(db, workplace="On-site") == [BANK]


def test_status_filter(db):
    application(db, BANK, "applied")
    application(db, AI, "interviewing")
    assert ids(db, status="applied") == [BANK]
    assert ids(db, status="any") == [AI, BANK]
    assert ids(db, status="none") == [ECON, SIMILAR]


def test_sorts(db):
    write(db, userdata.set_rating, SIMILAR, "interest", 5)
    write(db, userdata.set_rating, BANK, "interest", 3)
    assert ids(db, sort="interest") == [SIMILAR, BANK, ECON, AI]
    assert ids(db, sort="first_seen") == [ECON, AI, SIMILAR, BANK]
    posted = ids(db, sort="posted")
    assert sorted(posted) == sorted([ECON, AI, SIMILAR, BANK])


def test_filters_from_args_round_trip():
    args = {"q": " pytorch ", "min_interest": "3", "sort": "interest", "dismissed": "only", "unrated": "1"}
    filters = ListFilters.from_args(args)
    assert filters == ListFilters(q="pytorch", min_interest=3, sort="interest", dismissed="only", unrated=True)
    assert ListFilters.from_args(filters.to_args()) == filters
    assert ListFilters.from_args({"min_interest": "9", "sort": "x", "status": "bogus"}) == ListFilters()
    assert ListFilters().to_args() == {}


# --- Detail and diff (5.2) ---


def test_detail_of_stored_posting(db):
    write(db, userdata.set_rating, BANK, "interest", 4)
    write(db, userdata.add_tag, BANK, "ml")
    write(db, userdata.dismiss, BANK, [reason(db, "too senior"), reason(db, "company")], "meh")
    write(db, userdata.add_skill_mark, BANK, "Automation", "drives data automation")
    with db.connect() as conn:
        detail = queries.posting_detail(conn, BANK)
    assert detail["posting"].url == "https://jobs.example.com/view/A-1001"
    assert detail["latest"].title == "Analytics Manager, Reporting Automation (Example City)"
    assert len(detail["snapshots"]) == 1 and len(detail["captures"]) == 1
    assert detail["triage"].interest == 4
    assert [t["name"] for t in detail["tags"]] == ["ml"]
    assert detail["dismissed"] and detail["dismissals"][0]["reasons"] == ["Too senior", "Company"]
    assert detail["marks"][0]["skill_name"] == "Automation" and detail["marks"][0]["found"]
    assert detail["application"] is None


def test_detail_unknown_job(db):
    with db.connect() as conn:
        assert queries.posting_detail(conn, 1234) is None


def test_detail_mark_not_found_after_change(db):
    write(db, userdata.add_skill_mark, BANK, "Automation", "drives data automation")
    add_posting(db, captured_at=at(25), tag="v2", description_html="<p>Rewritten.</p>", description_text="Rewritten.")
    with db.connect() as conn:
        detail = queries.posting_detail(conn, BANK)
    assert len(detail["snapshots"]) == 2
    assert detail["marks"][0]["found"] is False


def test_edited_description_diff(db):
    base = "Intro paragraph.\nOld requirement.\nClosing paragraph."
    add_posting(db, captured_at=at(25), tag="a", description_text=base)
    add_posting(
        db,
        captured_at=at(26),
        tag="b",
        description_text=base.replace("Old", "New"),
        location="Remote",
        details={
            "apply_method": "external",
            "promotion": "Promoted by hirer",
            "reposted": False,
            "contract_length": "1 year",
        },
    )
    with db.connect() as conn:
        snaps = queries.posting_detail(conn, BANK)["snapshots"]
        diff = queries.snapshot_diff(conn, BANK, snaps[-2].id, snaps[-1].id)
        assert queries.snapshot_diff(conn, AI, snaps[-2].id, snaps[-1].id) is None
    assert diff["lines"] == [
        ("equal", "Intro paragraph."),
        ("delete", "Old requirement."),
        ("insert", "New requirement."),
        ("equal", "Closing paragraph."),
    ]
    assert diff["fields"] == [
        ("Location", "Example City, EX", "Remote"), ("Contract length", None, "1 year"), ("Reposted", True, False)
    ]


def test_search_by_external_id(db):
    with db.connect() as conn:
        assert [r["job_id"] for r in queries.posting_list(conn, ListFilters(q="A-1003"))] == [AI]
        assert [r["job_id"] for r in queries.posting_list(conn, ListFilters(q=" 1002 "))] == [SIMILAR]
        assert queries.posting_list(conn, ListFilters(q="A-10")) == []  # exact, not a substring


def test_detail_has_source_external_id_and_details(db):
    with db.connect() as conn:
        detail = queries.posting_detail(conn, BANK)
    assert (detail["posting"].source, detail["posting"].external_id) == ("jobs.example.com", "A-1001")
    assert detail["details"] == {"apply_method": "external", "promotion": "Promoted by hirer", "reposted": True}
    assert detail["volatile_details"] == {"applicants": "30 applicants", "posted_age": "6 days ago"}


# --- Skills page (5.3) ---


def test_skills_counts(db):
    for job in (BANK, AI, ECON):
        write(db, userdata.add_skill_mark, job, "PyTorch", "a" if job == ECON else "e")
    write(db, userdata.add_skill_mark, BANK, "pytorch", "again")  # same posting twice counts once
    write(db, userdata.get_or_create_skill, "Rust")
    write(db, userdata.set_rating, BANK, "interest", 4)
    write(db, userdata.set_rating, AI, "interest", 5)
    write(db, userdata.set_rating, ECON, "interest", 3)
    with db.connect() as conn:
        overview = queries.skills_overview(conn)
    assert [(s["name"], s["postings"], s["high_interest"]) for s in overview] == [("PyTorch", 3, 2), ("Rust", 0, 0)]
