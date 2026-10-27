"""Posting skills, embeddings and the shortlist, link-judge, effective links, overrides and the plan."""

import json

import pytest
from sqlalchemy import select

from jobhunt import queries, userdata
from jobhunt.db import link_judgments, link_relations, skill_embeddings, skills
from jobhunt.enrich import derived, links
from jobhunt.enrich.pipeline import Cancelled, StepFailed

from .conftest import add_posting, add_run
from .fakes import FakeOllama
from .test_profile import rows
from .test_userdata import write

BANK, SIMILAR, AI = 1, 2, 3  # keys in the order the db fixture imports them
EMBED = "nomic-embed-text:latest"


@pytest.fixture
def db(engine):
    assert add_posting(engine, "data-automation.json") == BANK
    assert add_posting(engine, "innovation-lab.json") == SIMILAR
    assert add_posting(engine, "senior-ai-engineer.json") == AI
    write(engine, userdata.set_setting, "llm.model", "gemma4:12b")
    return engine


def mark(engine, job, name, quote="Design", importance=None):
    return write(engine, userdata.add_skill_mark, job, name, quote, importance=importance)


def profile(engine, *names, level="proficient"):
    return [write(engine, userdata.add_profile_skill, name, level) for name in names]


def relations_answer(*relations):
    return {"relations": [{"candidate": n, "relation": r} for n, r in enumerate(relations, start=1)]}


def judging(*answers, vectors=None):
    """A model client answering link-judge requests in order (the last repeating)."""
    return FakeOllama(responses={"relations": list(answers)} if answers else None, vectors=vectors)


def judge(engine, client, everything=False, should_stop=lambda: False, model="gemma4:12b"):
    return links.judge_links(engine, client, model, 8192, EMBED, everything, should_stop)


def link_of(engine, key):
    with engine.connect() as conn:
        return queries.effective_link(conn, key)


def axis(*weights):
    """A unit-ish vector for explicit similarities."""
    return [float(w) for w in weights]


# --- Posting skills (7.1) ---


def test_marks_and_suggestions_combined(db):
    mark(db, AI, "Python", "Python", "required")
    add_run(
        db,
        AI,
        skills=[("python", "preferred", "Python"), ("ReactJS", "required", "ReactJS"), ("AWS", "required", "AWS")],
    )
    write(db, userdata.reject_suggestion, AI, "AWS", "not-for-me")
    with db.connect() as conn:
        found = queries.posting_skills(conn, AI)
    assert [(s["name"], s["importance"], s["source"]) for s in found] == [
        ("Python", "required", "mark"), ("ReactJS", "required", "suggestion")
    ]


def test_unverified_suggestion_left_out(db):
    add_run(db, AI, skills=[("Terraform", "required", "Terraform modules"), ("AWS", "required", "AWS")])
    with db.connect() as conn:
        assert [s["key"] for s in queries.posting_skills(conn, AI)] == ["aws"]


def test_run_on_an_older_snapshot_ignored(db):
    add_run(db, BANK, skills=[("Data lineage", "required", "data lineage")])
    add_posting(db, "data-automation.json", tag="changed", description_text="A new description about Rust.")
    with db.connect() as conn:
        assert queries.posting_skills(conn, BANK) == []


def test_eval_run_left_out(db):
    mark(db, AI, "Python", "Python", "required")
    add_run(db, AI, skills=[("Prompt engineering", "required", "Python")], origin="eval")
    with db.connect() as conn:
        assert [(s["name"], s["source"]) for s in queries.posting_skills(conn, AI)] == [("Python", "mark")]
        assert [k["key"] for k in queries.posting_skill_keys(conn)] == ["python"]


def test_mark_at_both_importances_is_required(db):
    mark(db, BANK, "Data lineage", "data lineage", "preferred")
    mark(db, BANK, "data lineage", "lineage", "required")
    with db.connect() as conn:
        [found] = queries.posting_skills(conn, BANK)
    assert (found["importance"], found["source"]) == ("required", "mark")


def test_posting_skill_keys_count_postings(db):
    for job in (BANK, SIMILAR, AI):
        mark(db, job, "Python")
    mark(db, AI, "Dask")
    add_run(db, BANK, skills=[("python", "required", "data")])  # marked already: counted once
    with db.connect() as conn:
        keys = queries.posting_skill_keys(conn)
    assert [(k["key"], k["name"], k["postings"]) for k in keys] == [("python", "Python", 3), ("dask", "Dask", 1)]


# --- Embeddings and the shortlist (7.2) ---


def test_vector_round_trip(db):
    vector = [0.5, -1.25, 3.0, 0.0]
    write(db, derived.save_embeddings, EMBED, {"python": vector})
    with db.connect() as conn:
        assert links.stored_vectors(conn, EMBED) == {"python": vector}
        assert len(conn.execute(select(skill_embeddings.c.vector)).scalar_one()) == 16


def test_names_embedded_once_per_model(db):
    mark(db, AI, "Python scripting", "Python")
    profile(db, "Python")
    client = judging(relations_answer("specific"))
    judge(db, client)
    assert client.embed_requests == [(EMBED, ["clustering: Python scripting", "clustering: Python"])]
    judge(db, client, everything=True)
    assert len(client.embed_requests) == 1
    links.judge_links(db, client, "gemma4:12b", 8192, "other-embed:latest")
    assert client.embed_requests[-1] == ("other-embed:latest", ["Python scripting", "Python"])  # no prefix known


def test_nothing_similar(db):
    mark(db, AI, "Salesforce")
    profile(db, "Python")
    client = FakeOllama()
    result = judge(db, client)
    assert (result.planned, result.requests) == (1, 0) and client.requests == []
    assert link_of(db, "salesforce")["skill_id"] is None
    [judgment] = rows(db, link_judgments)
    assert json.loads(judgment.candidates_json) == [] and judgment.status == "succeeded"


def test_shortlist_keeps_the_most_similar_above_the_floor(db):
    names = ["A", "B", "C", "D", "E", "F", "G"]
    vectors = {n: axis(1, i) for i, n in enumerate(names)}  # similarity to (1, 0) falls with i
    rows_ = [type("Row", (), {"id": i, "name": n}) for i, n in enumerate(names)]
    found = links.shortlist(axis(1, 0), [(r, vectors[r.name]) for r in rows_])
    assert [c.name for c in found] == ["A"]  # B is at cos 0.707, under the floor
    with_floor = links.shortlist(axis(1, 0.01), [(r, axis(1, 0.01 * i)) for r in rows_ for i in [r.id]])
    assert len(with_floor) == links.SHORTLIST_K


def test_embedding_failure_stores_nothing(db):
    mark(db, AI, "Python scripting", "Python")
    profile(db, "Python")
    client = FakeOllama()
    client.embed_failure = "asked for 2 embeddings and got 1"
    with pytest.raises(StepFailed):
        judge(db, client)
    assert rows_of(db, skill_embeddings) == [] and rows(db, link_judgments) == []


def rows_of(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table)).all()


# --- link-judge (7.3) ---


@pytest.fixture
def anything_goes(monkeypatch):
    monkeypatch.setattr(links, "SHORTLIST_FLOOR", -1.0)


def test_specific_form(db, anything_goes):
    mark(db, AI, "CI/CD")
    [actions] = profile(db, "GitHub Actions")
    client = judging(relations_answer("specific"))
    judge(db, client)
    link = link_of(db, "ci/cd")
    assert (link["skill_id"], link["relation"], link["source"]) == (actions, "specific", "model")
    [request] = client.requests
    assert request.key == "relations" and "Posting skill: CI/CD" in request.user and "1: GitHub Actions" in request.user
    assert request.model == "gemma4:12b"


def test_strongest_relation_wins(db, anything_goes):
    mark(db, AI, "LoRA")
    fine_tuning, llms = profile(db, "LLM fine-tuning", "Large language models")
    vectors = {"LoRA": axis(1, 0), "LLM fine-tuning": axis(1, 0.5), "Large language models": axis(1, 0.1)}
    client = judging(relations_answer("related", "general"), vectors=vectors)
    judge(db, client)
    assert "1: Large language models" in client.requests[0].user  # the most similar comes first
    link = link_of(db, "lora")
    assert (link["skill_id"], link["relation"]) == (fine_tuning, "general")


def test_every_usable_relation_is_an_option(db, anything_goes):
    mark(db, AI, "LoRA")
    fine_tuning, llms, rust = profile(db, "LLM fine-tuning", "Large language models", "Rust")
    vectors = {"LoRA": axis(1, 0), "LLM fine-tuning": axis(1, 0.5), "Large language models": axis(1, 0.1),
               "Rust": axis(1, 0.9)}
    judge(db, judging(relations_answer("related", "general", "none"), vectors=vectors))
    link = link_of(db, "lora")
    assert (link["skill_id"], link["relation"]) == (fine_tuning, "general")
    assert link["options"] == [
        {"skill_id": fine_tuning, "relation": "general"}, {"skill_id": llms, "relation": "related"}
    ]


def test_options_of_overrides_and_same_identity(db):
    mark(db, AI, "Python")
    mark(db, AI, "Spark")
    mark(db, AI, "MLOps")
    python, pyspark = profile(db, "Python", "PySpark")
    write(db, userdata.set_link_override, "Spark", pyspark, "specific")
    write(db, userdata.set_link_override, "MLOps", None)
    assert link_of(db, "python")["options"] == [{"skill_id": python, "relation": "same"}]
    assert link_of(db, "spark")["options"] == [{"skill_id": pyspark, "relation": "specific"}]
    assert link_of(db, "mlops")["options"] == []


def test_candidates_left_out_are_none_and_quotes_give_context(db, anything_goes):
    mark(db, AI, "Python scripting", "Work with Python")
    python, rust = profile(db, "Python", "Rust")
    highlight = write(db, userdata.add_highlight, "8+ years experience with Python")
    write(db, userdata.add_coverage, highlight, python, "8+ years experience with Python")
    client = judging({"relations": [{"candidate": 1, "relation": "specific"}, {"candidate": 9, "relation": "same"}]})
    judge(db, client)
    assert 'In the posting: "Work with Python"' in client.requests[0].user
    assert '(on the CV: "8+ years experience with Python")' in client.requests[0].user
    assert {(r.skill_id, r.relation) for r in rows_of(db, link_relations)} == {(python, "specific"), (rust, "none")}


def test_judge_shown_the_cv_line(db, anything_goes, monkeypatch):
    """@6 shows the line the context quote was found in: the ground's record line holding it (else the record's
    title and organisation), or the covering highlight's text."""
    monkeypatch.setattr(links, "JUDGE", links.JUDGES["link-judge@6"])
    mark(db, AI, "Python scripting", "Work with Python")
    mark(db, AI, "Teaching", "Teach new hires")
    mark(db, AI, "Pipelines", "Build pipelines")
    python, lecturing, cicd = profile(db, "Python", "Lecturing", "CI/CD")
    parking = write(db, userdata.add_record, {"kind": "project", "title": "city-parking"})
    write(db, userdata.add_line, parking, "Parking enforcement tool")
    write(db, userdata.add_line, parking, "Technologies: Python, Flask, PostgreSQL")
    write(db, userdata.add_ground, python, parking, "Python")
    course = write(
        db,
        userdata.add_record,
        {"kind": "course", "title": "Sessional Instructor", "organisation": "Example University"},
    )
    write(db, userdata.add_ground, lecturing, course, "Instructor")
    highlight = write(db, userdata.add_highlight, "Familiar with serverless CI/CD")
    write(db, userdata.add_coverage, highlight, cicd, "CI/CD")
    client = judging(relations_answer("specific", "none"))
    judge(db, client)
    requests = "\n".join(r.user for r in client.requests)
    assert '(on the CV: "Technologies: Python, Flask, PostgreSQL")' in requests
    assert '(on the CV: "Sessional Instructor, Example University")' in requests
    assert '(on the CV: "Familiar with serverless CI/CD")' in requests
    assert "the CV line it was found in" in client.requests[0].system


def test_long_cv_lines_cut_around_the_quote():
    line = (
        "A Flask service with a task queue (Celery + Redis) that polls weather stations hourly and stores each reading"
    )
    assert links.around(line, "Redis", 40) == "… queue (Celery + Redis) that polls weath…"  # centred on the quote
    assert links.around(line, "Kafka", 20) == "A Flask service with…"
    assert links.around("Short line", "Short", 40) == "Short line"


def test_re_judging_keeps_history(db, anything_goes):
    mark(db, AI, "CI/CD")
    [actions] = profile(db, "GitHub Actions")
    judge(db, judging(relations_answer("related")))
    judge(db, judging(relations_answer("specific")), everything=True)
    assert [j.status for j in rows(db, link_judgments)] == ["succeeded", "succeeded"]
    assert link_of(db, "ci/cd")["relation"] == "specific"


def test_failed_judgment_keeps_the_previous_one(db, anything_goes):
    mark(db, AI, "CI/CD")
    profile(db, "GitHub Actions")
    judge(db, judging(relations_answer("specific")))
    result = judge(db, judging({"relations": [{"candidate": "one"}]}), everything=True)
    assert (result.failed, [j.status for j in rows(db, link_judgments)]) == (1, ["succeeded", "failed"])
    assert link_of(db, "ci/cd")["relation"] == "specific"


def test_judge_prompt_version():
    assert links.PIPELINE == "links=link-judge@5"
    assert "most are \"none\"" in links.JUDGE_SYSTEM and "choose the weaker one" in links.JUDGE_SYSTEM


def test_cancelled_between_keys_keeps_finished_judgments(db, anything_goes):
    mark(db, AI, "CI/CD")
    mark(db, AI, "MLOps")
    profile(db, "Docker")
    client = judging(relations_answer("related"))
    with pytest.raises(Cancelled):
        judge(db, client, should_stop=lambda: len(client.requests) >= 1)
    assert len(rows(db, link_judgments)) == 1
    result = judge(db, client)
    assert result.planned == 1  # only the key not yet judged


# --- Effective links and overrides (7.4) ---


def test_same_identity(db):
    mark(db, AI, "python")
    [python] = profile(db, "Python")
    client = FakeOllama()
    assert judge(db, client).planned == 0 and client.requests == []
    link = link_of(db, "python")
    assert (link["skill_id"], link["relation"], link["source"]) == (python, "same", "same")


def test_alias(db, anything_goes):
    mark(db, AI, "Postgres")
    [postgresql] = profile(db, "PostgreSQL")
    with db.connect() as conn:
        postgres = queries.resolve_skill(conn, "postgres").id
    write(db, userdata.merge_skill, postgres, postgresql)
    client = FakeOllama()
    assert judge(db, client).planned == 0 and client.requests == []
    link = link_of(db, "postgres")
    assert (link["skill_id"], link["skill_name"], link["relation"], link["source"]) == (
        postgresql, "PostgreSQL", "same", "same",
    )


def test_link_used_before_review(db, anything_goes):
    mark(db, AI, "CI/CD")
    profile(db, "GitHub Actions")
    judge(db, judging(relations_answer("specific")))
    with db.connect() as conn:
        [row] = queries.links_overview(conn)
    assert (row["name"], row["link"]["skill_name"], row["link"]["source"]) == ("CI/CD", "GitHub Actions", "model")


def test_overriding_a_model_link(db, anything_goes):
    mark(db, AI, "MLOps")
    profile(db, "Docker")
    judge(db, judging(relations_answer("related")))
    assert link_of(db, "mlops")["skill_name"] == "Docker"
    write(db, userdata.set_link_override, "MLOps", None)
    link = link_of(db, "mlops")
    assert (link["skill_id"], link["source"]) == (None, "user")
    client = judging(relations_answer("same"))
    assert judge(db, client, everything=True).planned == 0 and client.requests == []
    assert link_of(db, "mlops")["source"] == "user"


def test_override_to_a_profile_skill(db):
    mark(db, AI, "Spark")
    [pyspark] = profile(db, "PySpark")
    write(db, userdata.set_link_override, "spark", pyspark, "specific")
    link = link_of(db, "spark")
    assert (link["skill_id"], link["relation"], link["source"]) == (pyspark, "specific", "user")
    with pytest.raises(userdata.UserDataError, match="relation must be one of"):
        write(db, userdata.set_link_override, "spark", pyspark, "cousin")
    mark(db, AI, "Rust")
    with db.connect() as conn:
        rust = conn.execute(select(skills.c.id).where(skills.c.key == "rust")).scalar_one()
    with pytest.raises(userdata.UserDataError, match="in the profile"):
        write(db, userdata.set_link_override, "spark", rust, "same")
    write(db, userdata.clear_link_override, "Spark")
    assert link_of(db, "spark")["source"] is None


def test_stale_override(db, anything_goes):
    mark(db, AI, "Spark")
    pyspark, scala = profile(db, "PySpark", "Scala")
    write(db, userdata.set_link_override, "Spark", pyspark, "specific")
    judge(db, FakeOllama())  # overridden: not judged
    write(db, userdata.remove_profile_skill, pyspark)
    link = link_of(db, "spark")
    assert (link["stale_override"], link["skill_id"], link["source"]) == ("PySpark", None, None)


def test_judged_relation_to_a_skill_that_left_the_profile_ignored(db, anything_goes):
    mark(db, AI, "CI/CD")
    actions, docker = profile(db, "GitHub Actions", "Docker")
    vectors = {"CI/CD": axis(1, 0), "GitHub Actions": axis(1, 0.1), "Docker": axis(1, 0.5)}
    judge(db, judging(relations_answer("specific", "related"), vectors=vectors))
    write(db, userdata.remove_profile_skill, actions)
    link = link_of(db, "ci/cd")
    assert (link["skill_name"], link["relation"]) == ("Docker", "related")


# --- The plan (7.5) ---


VECTORS = {
    "CI/CD": axis(1, 0, 0), "Kubernetes": axis(0, 1, 0), "Docker": axis(0.2, 1, 0),
    "Jenkins": axis(0.8, 0.1, 0.1), "GitHub Actions": axis(1, 0.05, 0),
}


def test_new_closer_profile_skill(db):
    mark(db, AI, "CI/CD")
    mark(db, AI, "Kubernetes")
    profile(db, "Docker", "Jenkins")
    client = judging(relations_answer("related"), vectors=VECTORS)
    judge(db, client)
    first = {j.posting_key: json.loads(j.candidates_json) for j in rows(db, link_judgments)}
    assert [c["name"] for c in first["ci/cd"]] == ["Jenkins"] and [c["name"] for c in first["kubernetes"]] == ["Docker"]

    profile(db, "GitHub Actions")
    with db.connect() as conn:
        planned = links.plan(conn, EMBED)  # GitHub Actions has no vector yet: nothing is ready to judge
    assert planned == []
    judge(db, client)
    judged = [j.posting_key for j in rows(db, link_judgments)]
    assert judged == ["ci/cd", "kubernetes", "ci/cd"]


def test_nothing_changed(db):
    mark(db, AI, "CI/CD")
    profile(db, "Jenkins")
    client = judging(relations_answer("related"), vectors=VECTORS)
    judge(db, client)
    calls = len(client.requests)
    result = judge(db, client)
    assert (result.planned, len(client.requests)) == (0, calls)


def test_chat_model_change_alone_plans_nothing(db):
    mark(db, AI, "CI/CD")
    profile(db, "Jenkins")
    judge(db, judging(relations_answer("related"), vectors=VECTORS))
    write(db, userdata.set_setting, "llm.model", "phi4:latest")
    with db.connect() as conn:
        assert links.plan(conn, EMBED) == []
        assert [p.key for p in links.plan(conn, EMBED, everything=True)] == ["ci/cd"]


def test_embedding_model_change_plans_again(db):
    mark(db, AI, "CI/CD")
    profile(db, "Jenkins")
    client = judging(relations_answer("related"), vectors=VECTORS)
    judge(db, client)
    result = links.judge_links(db, client, "gemma4:12b", 8192, "other-embed:latest")
    assert result.planned == 1


def test_empty_profile_plans_nothing(db):
    mark(db, AI, "CI/CD")
    client = FakeOllama()
    assert judge(db, client).planned == 0 and client.embed_requests == []


def test_effective_links_report_whether_judged(db):
    mark(db, AI, "Terraform")
    mark(db, AI, "AWS")
    mark(db, AI, "Ansible")
    profile(db, "Python")
    write(db, userdata.set_link_override, "Ansible", None)
    with db.connect() as conn:
        found = queries.effective_links(conn, ["terraform", "aws", "ansible"])
    assert [found[k]["judged"] for k in ("terraform", "aws", "ansible")] == [False, False, False]
    judge(db, judging(relations_answer("none")))
    with db.connect() as conn:
        found = queries.effective_links(conn, ["terraform", "aws", "ansible"])
    assert found["terraform"]["judged"] is True and found["terraform"]["options"] == []
