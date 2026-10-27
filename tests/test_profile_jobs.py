"""The queue's document and links jobs, and what queues link judging automatically."""

import pytest
from sqlalchemy import select, update

from jobhunt import queries, userdata
from jobhunt.db import claims, document_runs, highlights, link_judgments, llm_jobs, profile_suggestions, records
from jobhunt.documents import StoredFile
from jobhunt.enrich import cv, jobs, links
from jobhunt.enrich.ollama import ModelInfo
from jobhunt.enrich.pipeline import Unreachable

from .conftest import add_posting, add_run
from .fakes import FakeOllama, label_lines, skill
from .test_cv_pipeline import CV_TEXT, ENTRIES, SKILLS, cv_skills_for, label_cv_lines
from .test_profile import rows
from .test_userdata import write

BANK, SIMILAR, AI = 1, 2, 3  # keys in the order the db fixture imports them


@pytest.fixture
def db(engine):
    assert add_posting(engine, "data-automation.json") == BANK
    assert add_posting(engine, "innovation-lab.json") == SIMILAR
    assert add_posting(engine, "senior-ai-engineer.json") == AI
    write(engine, userdata.set_setting, "llm.model", "gemma4:12b")
    return engine


def add_cv(engine, text=CV_TEXT, kind="cv", label="CV"):
    stored = StoredFile("c" * 64, len(text or ""), "cv.odt", "application/vnd.oasis.opendocument.text", text,
                        "extracted" if text else "failed: BadZipFile")
    return write(engine, userdata.add_document, stored, label, kind)


def lines_for_both(user: str) -> dict:
    """Posting segmenter answers for the bank posting; CV line labels for anything else."""
    if "data lineage" in user:
        return label_lines({"data lineage": "required"})(user)
    return label_cv_lines(ENTRIES)(user)


def model_client(**kwargs):
    return FakeOllama(
        responses={
            "lines": [lines_for_both],
            "skills": [{"skills": [skill(1, "Data lineage", "data lineage")]}],
            "cv_skills": [cv_skills_for(SKILLS)],
            "relations": [{"relations": [{"candidate": 1, "relation": "related"}]}],
        },
        **kwargs,
    )


def job_rows(engine):
    with engine.connect() as conn:
        return conn.execute(select(llm_jobs).order_by(llm_jobs.c.id)).all()


def queued_links(engine):
    return [j for j in job_rows(engine) if j.kind == "links" and j.status == "queued"]


def clear_queue(engine):
    write(engine, jobs.cancel_all)
    with engine.begin() as conn:
        conn.execute(update(llm_jobs).where(llm_jobs.c.finished_at.is_(None)).values(finished_at=userdata.utcnow()))


# --- Document jobs (8.1) ---


def profile_rows(engine) -> int:
    return sum(len(rows(engine, t)) for t in (records, claims, highlights))


def test_document_extraction_alone(db):
    document_id = add_cv(db)
    job_id, added = write(db, jobs.enqueue_document, document_id)
    assert added and write(db, jobs.enqueue_document, document_id) == (job_id, False)
    assert jobs.run_next(db, model_client()) == "done"
    [job] = [j for j in job_rows(db) if j.kind == "document"]
    [run] = rows(db, document_runs)
    assert (job.document_run_id, run.pipeline, run.model, run.status) == (
        run.id,
        cv.pipeline_id(),
        "gemma4:12b",
        "succeeded",
    )
    assert {s.kind for s in rows(db, profile_suggestions)} == {"record", "claim", "highlight"}
    assert profile_rows(db) == 0  # suggestions only: the profile waits for the user
    assert queued_links(db) == []


def test_failed_document_run_stores_no_suggestions(db):
    write(db, jobs.enqueue_document, add_cv(db))
    client = model_client()
    client.responses["cv_skills"] = [{"cv_skills": [{"line": 1}]}]
    assert jobs.run_next(db, client) == "failed"
    [job] = job_rows(db)
    [run] = rows(db, document_runs)
    assert run.status == "failed" and job.error == run.error and job.document_run_id == run.id
    assert rows(db, profile_suggestions) == [] and profile_rows(db) == 0 and queued_links(db) == []


def test_queued_job_with_the_old_pipeline_fails(db):
    write(db, jobs.enqueue_document, add_cv(db))
    with db.begin() as conn:
        conn.execute(update(llm_jobs).values(pipeline="cvseg=caps@1 cvlines=llm@1 cvskills=cv-atomic@1 validate=v@3"))
    assert jobs.run_next(db, model_client()) == "failed"
    [job] = job_rows(db)
    assert "not available in this version" in job.error and rows(db, document_runs) == []


def test_document_without_text_refused(db):
    with pytest.raises(userdata.UserDataError, match="no extracted text"):
        write(db, jobs.enqueue_document, add_cv(db, text=None))


def test_document_job_cancelled_mid_run_stores_nothing(db):
    write(db, jobs.enqueue_document, add_cv(db))

    def cancel(key):
        if key == "lines":
            write(db, jobs.cancel_all)

    assert jobs.run_next(db, model_client(on_call=cancel)) == "cancelled"
    assert rows(db, document_runs) == [] and rows(db, profile_suggestions) == []


def accept_a_claim(engine) -> None:
    with engine.connect() as conn:
        offer = queries.profile_suggestions(conn)["claim"][0]
    write(engine, userdata.accept_profile_suggestion, offer["id"])


def test_mixed_kinds_in_order(db):
    write(db, jobs.enqueue, BANK)
    write(db, jobs.enqueue_document, add_cv(db))
    client = model_client()
    assert [jobs.run_next(db, client) for _ in range(3)] == ["done", "done", None]
    accept_a_claim(db)
    assert jobs.run_next(db, client) == "done"
    assert [(j.kind, j.status) for j in job_rows(db)] == [("posting", "done"), ("document", "done"), ("links", "done")]
    kinds_asked = [r.key for r in client.requests]
    assert kinds_asked.index("cv_skills") > kinds_asked.index("skills")
    with db.connect() as conn:
        subjects = [(j["kind"], j["document_label"], j["title"]) for j in queries.queue_overview(conn)["recent"]]
    assert [s[0] for s in subjects] == ["links", "document", "posting"] and subjects[1][1] == "CV"


def test_cancelling_link_judging_midway(db, monkeypatch):
    from jobhunt.enrich import links

    monkeypatch.setattr(links, "SHORTLIST_FLOOR", -1.0)
    for name in ("CI/CD", "MLOps", "Terraform", "Spark"):
        write(db, userdata.add_skill_mark, AI, name, "Design")
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    calls = []

    def cancel_after_two(key):
        calls.append(key)
        if len(calls) == 2:
            write(db, jobs.cancel_all)

    assert jobs.run_next(db, model_client(on_call=cancel_after_two)) == "cancelled"
    assert len(rows(db, link_judgments)) == 2
    write(db, jobs.enqueue_links)
    client = model_client()
    assert jobs.run_next(db, client) == "done"
    assert len(rows(db, link_judgments)) == 4 and client.calls("relations") == 2


def test_links_job_waits_without_an_embedding_model(db):
    write(db, userdata.add_profile_skill, "Docker", "proficient")  # queues links
    write(db, jobs.enqueue, BANK)
    client = model_client(models=[ModelInfo("gemma4:12b", "d1", 1, ("completion",))])
    assert jobs.run_next(db, client) == "done"  # the posting job, queued after, runs first
    assert jobs.run_next(db, client) is None
    assert [j.status for j in job_rows(db) if j.kind == "links"] == ["queued"]
    client.installed.append(ModelInfo("nomic-embed-text:latest", "d3", 1, ("embedding",)))
    assert jobs.run_next(db, client) == "done"


def test_links_job_requeued_while_unreachable(db):
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    write(db, userdata.add_skill_mark, AI, "Docker Compose", "Design")
    client = model_client()
    jobs_before = job_rows(db)
    client.unreachable = True
    with pytest.raises(Unreachable):
        jobs.run_next(db, client)
    assert [j.status for j in job_rows(db)] == [j.status for j in jobs_before]


def test_embedding_failure_fails_the_links_job(db):
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    client = model_client()
    client.embed_failure = "asked nomic-embed-text:latest for 1 embeddings and got 0"
    assert jobs.run_next(db, client) == "failed"
    assert job_rows(db)[-1].error == "embed: asked nomic-embed-text:latest for 1 embeddings and got 0"


def test_rejudge_all_widens_the_queued_job(db):
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    [queued] = queued_links(db)
    assert write(db, jobs.enqueue_links, everything=True) == queued.id
    assert queued_links(db)[0].pipeline == links.PIPELINE + links.ALL_SCOPE


# --- What queues link judging (8.2) ---


def test_no_links_job_without_profile_skills_or_a_model(engine):
    add_posting(engine)
    write(engine, userdata.add_skill_mark, BANK, "Python", "Design")
    assert job_rows(engine) == []
    write(engine, userdata.add_profile_skill, "Python", "expert")  # still no chat model
    assert job_rows(engine) == []


def test_changes_coalesce(db):
    for name in ("Docker", "Rust", "Go"):
        write(db, userdata.add_profile_skill, name, "proficient")
    assert len(queued_links(db)) == 1


def test_running_links_job_gets_a_successor(db):
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    jobs._claim(db, model_client())
    write(db, userdata.add_profile_skill, "Rust", "proficient")
    assert [j.status for j in job_rows(db)] == ["running", "queued"]


@pytest.fixture
def ready(db):
    """Profile skills exist and the queue is empty: any trigger shows as a new queued links job."""
    write(db, userdata.add_profile_skill, "Docker", "proficient")
    write(db, userdata.add_profile_skill, "Kubernetes", "learning")
    write(db, userdata.add_skill_mark, AI, "Python", "Python")
    clear_queue(db)
    return db


def suggested(db):
    write(db, jobs.enqueue_document, add_cv(db))
    jobs.run_next(db, model_client())
    clear_queue(db)
    accept_a_claim(db)


def grounded(db):
    record = write(db, userdata.add_record, {"kind": "project", "title": "city-parking"})
    clear_queue(db)
    write(db, userdata.add_ground, _skill(db, "docker"), record)


TRIGGERS = {
    "accept a claim suggestion": suggested,
    "add profile skill": lambda db: write(db, userdata.add_profile_skill, "Rust", "learning"),
    "rename profile skill": lambda db: write(db, userdata.rename_skill, _skill(db, "docker"), "Docker Engine"),
    "remove profile skill": lambda db: write(db, userdata.remove_profile_skill, _skill(db, "docker")),
    "level from skills page": lambda db: write(db, userdata.set_skill_level, _skill(db, "python"), "learning"),
    "add ground": grounded,
    "merge skill": lambda db: write(db, userdata.merge_skill, _skill(db, "kubernetes"), _skill(db, "docker")),
    "add mark": lambda db: write(db, userdata.add_skill_mark, BANK, "Data lineage", "data lineage"),
    "remove mark": lambda db: write(db, userdata.remove_skill_mark, _mark(db)),
    "reject": lambda db: write(db, userdata.reject_suggestion, BANK, "LangChain", "not-a-skill"),
    "embedding model": lambda db: write(db, userdata.set_setting, "llm.embed_model", "nomic-embed-text:latest"),
}


def _skill(db, key):
    from jobhunt.db import skills

    with db.connect() as conn:
        return conn.execute(select(skills.c.id).where(skills.c.key == key)).scalar_one()


def _mark(db):
    from jobhunt.db import posting_skill_marks

    with db.connect() as conn:
        return conn.execute(select(posting_skill_marks.c.id)).scalar()


@pytest.mark.parametrize("trigger", list(TRIGGERS))
def test_trigger_queues_link_judging(ready, trigger):
    TRIGGERS[trigger](ready)
    assert len(queued_links(ready)) == 1


def test_unreject_queues_link_judging(ready):
    write(ready, userdata.reject_suggestion, BANK, "LangChain", "not-a-skill")
    clear_queue(ready)
    write(ready, userdata.unreject_suggestion, BANK, "LangChain")
    assert len(queued_links(ready)) == 1
    clear_queue(ready)
    write(ready, userdata.unreject_suggestion, BANK, "LangChain")  # nothing to undo: nothing queued
    assert queued_links(ready) == []


def test_successful_posting_run_queues_link_judging(ready):
    write(ready, jobs.enqueue, BANK)
    assert jobs.run_next(ready, model_client()) == "done"
    assert len(queued_links(ready)) == 1


def test_failed_posting_run_queues_nothing(ready):
    write(ready, jobs.enqueue, BANK)
    client = model_client()
    client.responses["skills"] = [{"skills": []}]
    assert jobs.run_next(ready, client) == "failed"
    assert queued_links(ready) == []


def test_unchanged_embedding_model_queues_nothing(ready):
    write(ready, userdata.set_setting, "llm.embed_model", "nomic-embed-text:latest")
    clear_queue(ready)
    write(ready, userdata.set_setting, "llm.embed_model", "nomic-embed-text:latest")
    assert queued_links(ready) == []


def test_removing_the_last_profile_skill_queues_nothing(db):
    docker = write(db, userdata.add_profile_skill, "Docker", "proficient")
    clear_queue(db)
    write(db, userdata.remove_profile_skill, docker)  # nothing left to link to
    assert queued_links(db) == []


def test_level_change_within_the_profile_queues_nothing(ready):
    write(ready, userdata.set_skill_level, _skill(ready, "docker"), "expert")
    assert queued_links(ready) == []


def test_accepting_a_suggestion_is_adding_a_mark(ready):
    from jobhunt.db import enrichment_skills

    add_run(ready, BANK, skills=[("Data lineage", "required", "data lineage")])
    with ready.connect() as conn:
        item_id = conn.execute(select(enrichment_skills.c.id)).scalar_one()
    write(ready, userdata.accept_suggestion, item_id)
    assert len(queued_links(ready)) == 1
