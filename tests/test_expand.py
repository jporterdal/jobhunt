"""Skill expansion, expansion contexts, phrase-pair shortlisting, the linking method
registries and the links job's expansion step."""

import json
import random

import pytest
from sqlalchemy import select

from jobhunt import queries, userdata
from jobhunt.db import link_judgments, skill_expansions, skills
from jobhunt.enrich import derived, expand, jobs, links
from jobhunt.enrich.pipeline import StepFailed

from .fakes import FakeLLM, FakeOllama
from .test_links import (
    AI,
    BANK,
    EMBED,
    axis,
    db,  # noqa: F401  (fixture)
    judge,
    link_of,
    mark,
    profile,
    relations_answer,
    rows_of,
)
from .test_profile_jobs import clear_queue, queued_links
from .test_userdata import T1, T2, T3, write


def phrasing(*answers):
    """A phrases response answering by the request's skill name; skills not listed get no phrasings."""
    table = dict(answers)

    def respond(user: str) -> dict:
        name = user.splitlines()[0].removeprefix("Skill: ")
        return {"phrases": table.get(name, [])}

    return respond


@pytest.fixture
def expanding(monkeypatch):
    """The app's method is skill-expand@1 with link-judge@5, with a shortlist that keeps anything."""
    monkeypatch.setattr(links, "CURRENT_RETRIEVAL", expand.STEP)
    monkeypatch.setattr(links, "PIPELINE", links.pipeline_for(expand.STEP, "link-judge@5"))
    monkeypatch.setitem(
        links.RETRIEVALS, expand.STEP, links.Retrieval(expand.STEP, expansion=expand.STEP, size=5, floor=-1.0)
    )


def stored_expansions(engine):
    with engine.connect() as conn:
        return conn.execute(select(skill_expansions).order_by(skill_expansions.c.id)).all()


# --- The expansion step (2.1) ---


def test_duplicate_phrasings_dropped():
    llm = FakeLLM({"phrases": [{"phrases": [
        "claude code", "AI coding agent", "AI coding agent",
        "a command-line AI coding assistant made by Anthropic for writing code",
    ]}]})
    phrases, raw = expand.EXPANDER.expand("posting", "Claude Code", None, llm)
    assert phrases == ["AI coding agent"] and len(raw["phrases"]) == 4


def test_eight_words_kept_nine_dropped_and_six_at_most():
    eight = "one two three four five six seven eight"
    assert expand.clean("X", [eight, eight + " nine"]) == [eight]
    assert expand.clean("X", [f"phrase {n}" for n in range(9)]) == [f"phrase {n}" for n in range(6)]
    assert expand.clean("X", ["  spaced   out  ", ""]) == ["spaced out"]


def test_ambiguous_name_read_in_context():
    llm = FakeLLM({"phrases": [{"phrases": ["attention mechanism"]}]})
    expand.EXPANDER.expand("posting", "Attention", "experience with attention mechanisms in transformers", llm)
    expand.EXPANDER.expand("profile", "Python", "8+ years experience with Python", llm)
    expand.EXPANDER.expand("profile", "Rust", None, llm)
    users = [r.user for r in llm.requests]
    assert users[0] == 'Skill: Attention\nIn the posting: "experience with attention mechanisms in transformers"'
    assert users[1] == 'Skill: Python\nOn the CV: "8+ years experience with Python"'
    assert users[2] == "Skill: Rust"


def test_response_that_does_not_fit_fails():
    with pytest.raises(StepFailed):
        expand.EXPANDER.expand("posting", "Docker", None, FakeLLM({"phrases": [{"phrases": "Docker Engine"}]}))


# --- Stored expansions (2.2) ---


def test_failed_expansion_not_returned(db):
    wanted = expand.Wanted("posting", "docker", "Docker", "Docker")
    write(db, derived.save_expansion, wanted, expand.STEP, "gemma4:12b", "failed", "expand: boom", [], {})
    with db.connect() as conn:
        assert expand.posting_expansions(conn) == {}
    write(db, derived.save_expansion, wanted, expand.STEP, "gemma4:12b", "succeeded", None, ["Docker Engine"], {})
    with db.connect() as conn:
        assert expand.posting_expansions(conn) == {"docker": ["Docker Engine"]}
        assert expand.posting_expansions(conn, "skill-expand@2") == {}


def test_expanded_once(db, expanding):
    mark(db, AI, "Docker", "Docker")
    profile(db, "Kubernetes")
    client = FakeOllama(responses={"phrases": [phrasing(("Docker", ["Docker Engine"]))]})
    judge(db, client)
    assert sorted((e.side, e.skill_key) for e in stored_expansions(db)) == [
        ("posting", "docker"),
        ("profile", "kubernetes"),
    ]
    mark(db, BANK, "docker", "Design")  # a new posting asks for it, with another quote
    judge(db, client, everything=True)
    assert client.calls("phrases") == 2


# --- Expansion contexts from grounds and highlights ---


def context_of(engine, key):
    with engine.connect() as conn:
        skill_id = conn.execute(select(skills.c.id).where(skills.c.key == key)).scalar_one()
        found = queries.expansion_contexts(conn).get(skill_id)
    return found[1] if found else None


def missing_profile(engine):
    with engine.connect() as conn:
        return [w for w in expand.missing(conn, [], queries.profile_skills(conn), queries.expansion_contexts(conn))]


def save_profile_expansion(engine, wanted):
    write(engine, derived.save_expansion, wanted, expand.STEP, "gemma4:12b", "succeeded", None, ["phrasing"], {})


def add_record(engine, title):
    return write(engine, userdata.add_record, {"kind": "project", "title": title})


@pytest.fixture
def grounded(db):
    """Python grounded by tidyplots (T1) and covered by a claims line (T2), with an expansion for that context."""
    [python] = profile(db, "Python")
    tidyplots = add_record(db, "tidyplots")
    write(db, userdata.add_ground, python, tidyplots, "Python", T1)
    highlight = write(db, userdata.add_highlight, "8+ years experience with Python")
    write(db, userdata.add_coverage, highlight, python, "8+ years experience with Python", T2)
    [wanted] = missing_profile(db)
    assert wanted.context == "Python"
    save_profile_expansion(db, wanted)
    return db, python, tidyplots


def test_a_later_ground_doesnt_change_the_context(grounded):
    db, python, _ = grounded
    write(db, userdata.add_ground, python, add_record(db, "price_tracker"), "Python 3", T3)
    assert context_of(db, "python") == "Python" and missing_profile(db) == []


def test_removing_the_oldest_ground(grounded):
    db, python, tidyplots = grounded
    write(db, userdata.remove_ground, python, tidyplots)
    assert context_of(db, "python") == "8+ years experience with Python"
    assert [w.context for w in missing_profile(db)] == ["8+ years experience with Python"]


def test_a_skill_added_by_hand(db):
    rust = write(db, userdata.add_profile_skill, "Rust", "learning")
    [wanted] = missing_profile(db)
    assert wanted.context is None
    save_profile_expansion(db, wanted)
    assert missing_profile(db) == []
    write(db, userdata.add_ground, rust, add_record(db, "A ray tracer in Rust"))
    assert [w.context for w in missing_profile(db)] == ["A ray tracer in Rust"]  # a hand-made ground quotes the record


def test_ties_go_to_grounds_and_unquoted_coverage_is_skipped(db):
    python, sql = profile(db, "Python", "SQL")
    highlight = write(db, userdata.add_highlight, "Python and SQL")
    write(db, userdata.add_coverage, highlight, python, "Python", T1)
    write(db, userdata.add_ground, python, add_record(db, "tidyplots"), "Python 3", T1)
    write(db, userdata.add_coverage, highlight, sql, None, T1)
    assert context_of(db, "python") == "Python 3"
    assert context_of(db, "sql") is None


# --- Registries, phrase-pair similarity and the links job (3.1-3.4) ---


def test_pipeline_ids():
    assert links.PIPELINE == "links=link-judge@5"
    assert links.pipeline_for(expand.STEP, "link-judge@6") == "expand=skill-expand@1 links=link-judge@6"
    assert links.judge_of("expand=skill-expand@1 links=link-judge@6") == "link-judge@6"
    assert links.judge_of("links=link-judge@2") == "link-judge@2"  # stored judgments name deleted versions too
    assert set(links.JUDGES) == {"link-judge@5", "link-judge@6"} and set(links.RETRIEVALS) == {"names", expand.STEP}


def test_names_shortlists_match_bare_name_cosines():
    rng = random.Random(7)
    query = [rng.uniform(-1, 1) for _ in range(16)]
    rows = [type("Row", (), {"id": i, "name": f"S{i}"}) for i in range(30)]
    vectors = {r.id: [rng.uniform(-1, 1) for _ in range(16)] for r in rows}
    found = links.shortlist(query, [(r, vectors[r.id]) for r in rows], size=8, floor=-1.0)
    expected = sorted(
        ((round(links.cosine(query, vectors[r.id]), 4), r.name) for r in rows), key=lambda x: (-x[0], x[1])
    )
    assert [(c.similarity, c.name) for c in found] == expected[:8] and all(c.pair is None for c in found)


def test_similar_meaning_different_spelling(db, expanding):
    mark(db, AI, "Claude Code", "Claude Code")
    [agentic, _] = profile(db, "agentic AI workflows", "Cooking")
    vectors = {
        "Claude Code": axis(1, 0, 0, 0), "agentic AI workflows": axis(0, 0, 1, 0), "Cooking": axis(0.3, 0, 0, 1),
        "AI coding agent": axis(0, 1, 0.1, 0), "AI agent workflows": axis(0, 1, 0, 0),
    }
    client = FakeOllama(
        responses={
            "phrases": [
                phrasing(("Claude Code", ["AI coding agent"]), ("agentic AI workflows", ["AI agent workflows"]))
            ],
            "relations": [relations_answer("related")],
        },
        vectors=vectors,
    )
    judge(db, client)
    [judgment] = rows_of(db, link_judgments)
    first, second = json.loads(judgment.candidates_json)
    assert (first["skill_id"], first["pair"]) == (agentic, ["AI coding agent", "AI agent workflows"])
    assert first["similarity"] == round(1 / 1.01 ** 0.5, 4) and second["name"] == "Cooking"
    assert judgment.pipeline == "expand=skill-expand@1 links=link-judge@5"
    assert link_of(db, "claude code")["skill_id"] == agentic


def test_failed_expansion_compares_by_name_and_retries(db, expanding):
    mark(db, AI, "Kubernetes", "Kubernetes")
    profile(db, "Docker")
    client = FakeOllama(responses={"phrases": [{"phrases": "not a list"}], "relations": [relations_answer("related")]})
    result = judge(db, client)
    assert (result.expand_failed, result.planned, result.judged) == (2, 1, 1)
    assert [e.status for e in stored_expansions(db)] == ["failed", "failed"]
    client.responses["phrases"] = [{"phrases": ["container orchestration"]}]
    result = judge(db, client)
    assert result.expanded == 2 and client.calls("phrases") == 4


def test_nothing_changed_with_expansion(db, expanding):
    mark(db, AI, "Kubernetes", "Kubernetes")
    profile(db, "Docker")
    client = FakeOllama(
        responses={"phrases": [{"phrases": ["container orchestration"]}], "relations": [relations_answer("related")]}
    )
    judge(db, client)
    calls = len(client.requests)
    assert judge(db, client).planned == 0 and len(client.requests) == calls
    judge(db, client, model="phi4:latest")  # another chat model neither re-expands nor re-judges
    assert len(client.requests) == calls


def test_new_linking_method_version(db, monkeypatch):
    mark(db, AI, "Kubernetes", "Kubernetes")
    [docker] = profile(db, "Docker")
    monkeypatch.setattr(links, "SHORTLIST_FLOOR", -1.0)
    judge(db, FakeOllama(responses={"relations": [relations_answer("related")]}))
    with db.connect() as conn:
        assert not links.outdated(conn)
    assert jobs.enqueue_links_if_outdated(db) is None

    monkeypatch.setattr(links, "CURRENT_JUDGE", "link-judge@6")
    monkeypatch.setattr(links, "JUDGE", links.JUDGES["link-judge@6"])
    monkeypatch.setattr(links, "PIPELINE", links.pipeline_for("names", "link-judge@6"))
    with db.connect() as conn:
        assert links.outdated(conn) and [p.key for p in links.plan(conn, EMBED)] == ["kubernetes"]
    assert (link_of(db, "kubernetes")["skill_id"], link_of(db, "kubernetes")["relation"]) == (docker, "related")
    client = FakeOllama(responses={"relations": [relations_answer("general")]})
    judge(db, client)
    assert links.JUDGE_SYSTEM_V6 == client.requests[0].system
    assert link_of(db, "kubernetes")["relation"] == "general"


def test_start_up_queues_judging_after_a_version_change(db, monkeypatch):
    mark(db, AI, "Kubernetes", "Kubernetes")
    profile(db, "Docker")
    judge(db, FakeOllama(responses={"relations": [relations_answer("related")]}))
    clear_queue(db)
    worker = jobs.Worker(db, FakeOllama())
    worker.stop()
    worker.run()  # nothing outdated: nothing queued at start-up
    assert queued_links(db) == []
    monkeypatch.setattr(links, "PIPELINE", links.pipeline_for("names", "link-judge@6"))
    worker = jobs.Worker(db, FakeOllama())
    worker.stop()
    worker.run()
    assert len(queued_links(db)) == 1


# The user's own links in the test fixtures: no prompt example may be one of them.
FIXTURE_OVERRIDES = {("Written communication", "Communication"), ("Git", "serverless CI/CD"),
                     ("Technical communication", "Communication"), ("Vector databases", None)}


def test_judge_examples_are_not_user_links():
    for method in links.JUDGES.values():
        assert '"Java" for "C#"' not in method.system and '"Operating systems" for "Docker"' not in method.system
        for posting, cv_skill in FIXTURE_OVERRIDES:
            if cv_skill is not None:
                assert f'"{cv_skill}" for "{posting}"' not in method.system
                assert f'"{posting}" and "{cv_skill}"' not in method.system
