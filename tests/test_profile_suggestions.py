"""Document suggestions for the profile: what is offered (queries.profile_suggestions), accepting, rejecting and
"Accept all" (userdata), on each configured database."""

import pytest
from sqlalchemy import update

from jobhunt import queries, userdata
from jobhunt.db import (
    claim_records,
    claims,
    highlight_claims,
    highlights,
    llm_jobs,
    profile_rejections,
    record_lines,
    records,
    skills,
)
from jobhunt.enrich import derived
from jobhunt.enrich.pipeline import DocumentResult
from jobhunt.userdata import UserDataError

from .test_profile import add_document, claim, grounds_of, record, rows
from .test_userdata import T1, T2, write


@pytest.fixture
def db(engine):
    return engine


def rec(title, kind="project", organisation=None, start=None, end=None, lines=(), sources=()):
    return {"kind": kind, "title": title, "organisation": organisation, "location": None, "start_date": start,
            "end_date": end, "ongoing": False, "lines": list(lines),
            "sources": [{"kind": userdata.source_kind(u), "url": u} for u in sources]}


def cl(name, level="proficient", grounds=(), coverage=()):
    return {"name": name, "level": level, "grounds": [{"record": r, "quote": q} for r, q in grounds],
            "coverage": [{"highlight": h, "quote": q} for h, q in coverage]}


def add_run(engine, document_id, records_=(), claims_=(), part_of=(), highlights_=(), status="succeeded"):
    suggestions = {
        "record": list(records_), "claim": list(claims_),
        "part_of": [{"record": a, "part_of": b} for a, b in part_of], "highlight": [{"text": t} for t in highlights_],
    }
    result = DocumentResult(status, None if status == "succeeded" else "skills: boom", T1, T1,
                            suggestions if status == "succeeded" else None, {"steps": []})
    return write(engine, derived.save_document_run, document_id, "f" * 64, "gemma4:12b", "p", result)


def offers(engine, kind=None):
    with engine.connect() as conn:
        found = queries.profile_suggestions(conn)
    return found if kind is None else found[kind]


def offer_for(engine, kind, **match):
    return next(o for o in offers(engine, kind) if all(o.get(k) == v for k, v in match.items()))


def accept(engine, offer, now=T2):
    return write(engine, userdata.accept_profile_suggestion, offer["id"], now)


def reject(engine, offer):
    write(engine, userdata.reject_profile_suggestion, offer["id"])


@pytest.fixture
def cv(db):
    """A CV run suggesting city-parking (with a line and its repository), Flask grounded by it, a claims line
    covering Python, and ml_basics grounding Python too."""
    doc = add_document(db)
    add_run(
        db,
        doc,
        [
            rec("city-parking", lines=["Technologies: Python, Flask"], sources=["https://github.com/x/city-parking"]),
            rec("ml_basics"),
        ],
        [
            cl("Flask", grounds=[(0, "Flask")]),
            cl("Python", "expert", grounds=[(1, "Python")], coverage=[(0, "Python")]),
        ],
        highlights_=["8+ years experience with Python"],
    )
    return db, doc


# --- What is offered ---


def test_new_suggestions_of_each_kind(cv):
    db, _ = cv
    found = offers(db)
    assert [(o["status"], o["label"], o["lines"], o["sources"]) for o in found["record"]][0][:2] == (
        "new",
        "city-parking",
    )
    flask = offer_for(db, "claim", name="Flask")
    assert (flask["status"], flask["level"], flask["grounds"], flask["waiting"]) == ("new", "proficient", [], 1)
    [highlight] = found["highlight"]
    assert (highlight["status"], highlight["covers"], highlight["waiting"]) == ("new", [], 1)  # Python has no claim yet
    assert found["part_of"] == [] and found["count"] == 5
    assert all(o["documents"] == ["CV"] for o in found["record"])


def test_same_record_in_two_documents(db):
    phd = rec("PhD Computer Science", "degree", "Example University", end="2022", lines=["Thesis"])
    add_run(db, add_document(db, "CV", sha="1" * 64), [phd])
    add_run(
        db,
        add_document(db, "portfolio", "other", sha="2" * 64),
        [
            rec(
                "phd computer science",
                "degree",
                " Example  University",
                end="2022",
                lines=["Thesis", "Supervisor: A. Smith"],
            )
        ],
    )
    [offer] = offers(db, "record")
    assert offer["documents"] == ["CV", "portfolio"] and len(offer["ids"]) == 2
    assert [ln["text"] for ln in offer["lines"]] == ["Thesis", "Supervisor: A. Smith"]


def test_suggestion_naming_an_alias(db):
    tracker = record(db, "price_tracker")
    parking = record(db, "city-parking")
    postgresql = write(db, userdata.add_profile_skill, "PostgreSQL", "proficient")
    write(db, userdata.add_ground, postgresql, parking)
    postgres = write(db, userdata.get_or_create_skill, "Postgres").id
    write(db, userdata.merge_skill, postgres, postgresql)
    add_run(db, add_document(db), [rec("price_tracker")], [cl("Postgres", grounds=[(0, "Postgres")])])
    [offer] = offers(db, "claim")
    assert (offer["status"], offer["name"], offer["claim_id"]) == ("adds", "PostgreSQL", claim(db, "postgresql").id)
    assert [g["record_id"] for g in offer["grounds"]] == [tracker]
    accept(db, offer)
    assert grounds_of(db, "postgresql") == sorted([tracker, parking]) and claim(db, "postgres") is None


def test_ground_waits_for_its_record(cv):
    db, _ = cv
    accept(db, offer_for(db, "claim", name="Flask"))
    assert claim(db, "flask") is not None and grounds_of(db, "flask") == []
    assert all(o["name"] != "Flask" for o in offers(db, "claim"))  # only waiting grounds left: not offered
    accept(db, offer_for(db, "record", label="city-parking"))
    flask = offer_for(db, "claim", name="Flask")
    assert flask["status"] == "adds" and [g["label"] for g in flask["grounds"]] == ["city-parking"]


def test_ground_on_a_rejected_record(cv):
    db, _ = cv
    reject(db, offer_for(db, "record", label="ml_basics"))
    python = offer_for(db, "claim", name="Python")
    assert python["waiting"] == 0 and python["grounds"] == []
    assert [o["label"] for o in offers(db, "record")] == ["city-parking"]


def test_user_level_kept(db):
    write(db, userdata.add_profile_skill, "Python", "proficient")
    add_run(db, add_document(db), claims_=[cl("Python", "expert")])
    assert offers(db, "claim") == []


def test_model_level_raised(db):
    add_run(db, add_document(db, sha="1" * 64), claims_=[cl("SQL", "familiar")])
    accept(db, offer_for(db, "claim", name="SQL"))
    assert (claim(db, "sql").level, claim(db, "sql").level_origin) == ("familiar", "model")
    add_run(db, add_document(db, "portfolio", sha="2" * 64), claims_=[cl("SQL", "proficient")])
    offer = offer_for(db, "claim", name="SQL")
    assert (offer["status"], offer["current_level"], offer["level"]) == ("adds", "familiar", "proficient")
    accept(db, offer)
    assert (claim(db, "sql").level, claim(db, "sql").level_origin) == ("proficient", "model")


def test_document_suggestion_after_triage(db):
    write(db, userdata.add_profile_skill, "Kubernetes", "missing")
    add_run(db, add_document(db), claims_=[cl("Kubernetes", "familiar")])
    assert offers(db, "claim") == [] and claim(db, "kubernetes").level == "missing"


def test_rerunning_a_document(cv):
    db, doc = cv
    for kind in ("record", "claim", "highlight", "claim"):
        write(db, userdata.accept_all_profile_suggestions, kind)
    assert offers(db)["count"] == 0
    add_run(
        db,
        doc,
        [
            rec("city-parking", lines=["Technologies: Python, Flask"], sources=["https://github.com/x/city-parking"]),
            rec("ml_basics"),
        ],
        [
            cl("Flask", grounds=[(0, "Flask")]),
            cl("Python", "expert", grounds=[(1, "Python")], coverage=[(0, "Python")]),
        ],
        highlights_=["8+ years experience with Python"],
    )
    assert offers(db)["count"] == 0


def test_record_offered_as_additions(db):
    parking = record(db, "city-parking")
    write(db, userdata.add_line, parking, "Technologies: Python, Flask")
    add_run(db, add_document(db), [rec("CITY-parking", lines=["technologies:  python, flask", "Won Best Design"])])
    [offer] = offers(db, "record")
    assert (offer["status"], offer["existing_id"], [ln["text"] for ln in offer["lines"]]) == (
        "adds",
        parking,
        ["Won Best Design"],
    )
    reject(db, offer)
    assert offers(db, "record") == [] and [ln.text for ln in rows(db, record_lines)] == ["Technologies: Python, Flask"]


def test_context_link_offered_once_both_records_exist(db):
    add_run(db, add_document(db), [rec("PhD thesis", "publication"), rec("PhD Computer Science", "degree")],
            part_of=[(0, 1)])
    assert offers(db, "part_of") == []
    write(db, userdata.accept_all_profile_suggestions, "record")
    [offer] = offers(db, "part_of")
    assert (offer["record_label"], offer["part_of_label"]) == ("PhD thesis", "PhD Computer Science")
    accept(db, offer)
    thesis = next(r for r in rows(db, records) if r.title == "PhD thesis")
    assert thesis.part_of_id is not None and thesis.origin == "suggestion" and offers(db, "part_of") == []


def test_context_link_refused_for_a_cycle(db):
    a, b = record(db, "A"), record(db, "B")
    write(db, userdata.set_part_of, b, a)
    add_run(db, add_document(db), [rec("A"), rec("B")], part_of=[(0, 1)])
    [offer] = offers(db, "part_of")
    with pytest.raises(UserDataError, match="part of itself"):
        accept(db, offer)
    assert write(db, userdata.accept_all_profile_suggestions, "part_of") == 0


def test_coverage_waits_for_its_claim(cv):
    db, _ = cv
    accept(db, offer_for(db, "highlight"))
    assert [h.text for h in rows(db, highlights)] == ["8+ years experience with Python"] and rows(
        db, highlight_claims
    ) == []
    accept(db, offer_for(db, "claim", name="Python"))
    [offer] = offers(db, "highlight")
    assert offer["status"] == "adds" and [c["name"] for c in offer["covers"]] == ["Python"]
    accept(db, offer)
    assert [(c.quote, c.origin) for c in rows(db, highlight_claims)] == [("Python", "suggestion")]


def test_extracting_twice_offers_the_latest_and_a_failed_run_changes_nothing(db):
    doc = add_document(db)
    add_run(db, doc, [rec("first run's record")])
    add_run(db, doc, [rec("second run's record")])
    assert [o["label"] for o in offers(db, "record")] == ["second run's record"]
    add_run(db, doc, status="failed")
    assert [o["label"] for o in offers(db, "record")] == ["second run's record"]


def test_deleted_skill_stays_deleted_and_forgetting_offers_it_again(db):
    chain = write(db, userdata.add_profile_skill, "Chain", "familiar")
    write(db, userdata.remove_profile_skill, chain)
    add_run(db, add_document(db), claims_=[cl("Chain")])
    assert offers(db, "claim") == []
    [rejection] = rows(db, profile_rejections)
    write(db, userdata.forget_rejection, rejection.id)
    assert [o["name"] for o in offers(db, "claim")] == ["Chain"] and claim(db, "chain") is None


# --- Accepting and rejecting ---


def test_accepting_a_claim(db):
    parking = record(db, "city-parking")
    add_run(db, add_document(db), [rec("city-parking")], [cl("Flask", grounds=[(0, "Flask")])])
    offer = offer_for(db, "claim", name="Flask")
    assert [g["record_id"] for g in offer["grounds"]] == [parking]
    assert accept(db, offer) == "claim"
    c = claim(db, "flask")
    assert (c.level, c.level_origin, c.origin, c.source_run_id) == (
        "proficient",
        "model",
        "suggestion",
        offer["run_id"],
    )
    [ground] = rows(db, claim_records)
    assert (ground.record_id, ground.quote, ground.origin) == (parking, "Flask", "suggestion")


def test_rejecting_a_non_skill(db):
    add_run(db, add_document(db, sha="1" * 64), claims_=[cl("(1+1)-ES")])
    reject(db, offer_for(db, "claim", name="(1+1)-ES"))
    assert claim(db, "(1+1)-es") is None and offers(db, "claim") == []
    add_run(db, add_document(db, "portfolio", sha="2" * 64), claims_=[cl("(1+1)-es")])
    assert offers(db, "claim") == []


def test_rejecting_additions_remembers_each(db):
    record(db, "city-parking")
    add_run(db, add_document(db, sha="1" * 64), claims_=[cl("SQL", "familiar")])
    accept(db, offer_for(db, "claim", name="SQL"))
    add_run(
        db,
        add_document(db, "portfolio", sha="2" * 64),
        [rec("city-parking")],
        [cl("SQL", "expert", grounds=[(0, "SQL")])],
    )
    offer = offer_for(db, "claim", name="SQL")
    assert offer["level"] == "expert" and len(offer["grounds"]) == 1
    reject(db, offer)
    assert offers(db, "claim") == [] and claim(db, "sql").level == "familiar" and grounds_of(db, "sql") == []
    labels = sorted(r.label for r in rows(db, profile_rejections))
    assert labels == ["SQL at expert", "SQL on city-parking"]


def test_accepting_all_records(db):
    first = [rec(f"project {n}") for n in range(15)]
    second = [rec(f"course {n}", "course") for n in range(15)]
    add_run(db, add_document(db, "CV", sha="1" * 64), first, [cl("Python", grounds=[(n, "Python") for n in range(15)])])
    add_run(db, add_document(db, "portfolio", sha="2" * 64), second, [cl("Teaching", grounds=[(0, "Teaching")])])
    assert write(db, userdata.accept_all_profile_suggestions, "record") == 30
    assert len(rows(db, records)) == 30 and all(r.origin == "suggestion" for r in rows(db, records))
    assert rows(db, claims) == []  # unlocked grounds are offered, not accepted
    python = offer_for(db, "claim", name="Python")
    assert (len(python["grounds"]), python["waiting"]) == (15, 0)
    assert write(db, userdata.accept_all_profile_suggestions, "claim") == 2
    assert len(grounds_of(db, "python")) == 15


def test_accepting_a_claim_suggestion_queues_link_judging(db):
    write(db, userdata.set_setting, "llm.model", "gemma4:12b")
    add_run(db, add_document(db), claims_=[cl("Docker")])
    accept(db, offer_for(db, "claim", name="Docker"))
    assert [(j.kind, j.status) for j in rows(db, llm_jobs)] == [("links", "queued")]


def test_document_extraction_leaves_the_profile_alone(db):
    add_run(db, add_document(db), [rec(f"r{n}") for n in range(12)], [cl(f"skill {n}") for n in range(40)])
    assert offers(db)["count"] == 52
    assert rows(db, records) == [] and rows(db, claims) == [] and rows(db, skills) == []


def test_accepting_an_offer_no_longer_offered(cv):
    db, _ = cv
    offer = offer_for(db, "record", label="ml_basics")
    accept(db, offer)
    with pytest.raises(UserDataError, match="no longer offered"):
        accept(db, offer)
    with pytest.raises(UserDataError):
        write(db, userdata.accept_all_profile_suggestions, "nonsense")


def test_accepting_never_changes_what_the_user_changed(db):
    parking = record(db, "city-parking")
    line = write(db, userdata.add_line, parking, "my own wording")
    with db.begin() as conn:
        conn.execute(update(records).values(origin="user"))
    add_run(db, add_document(db), [rec("city-parking", lines=["model wording"])])
    accept(db, offer_for(db, "record"))
    assert [(ln.text, ln.origin) for ln in rows(db, record_lines)] == [
        ("my own wording", "user"),
        ("model wording", "suggestion"),
    ]
    assert rows(db, records)[0].origin == "user" and line in {ln.id for ln in rows(db, record_lines)}
