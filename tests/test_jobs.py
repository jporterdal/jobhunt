"""The llm_jobs queue, run_next and the worker thread, against FakeLLM on each configured database."""

import time

import pytest
from sqlalchemy import event, select

from jobhunt import userdata
from jobhunt.db import app_settings, llm_jobs, posting_enrichments
from jobhunt.enrich import jobs
from jobhunt.enrich.pipeline import Unreachable
from jobhunt.queries import ListFilters
from jobhunt.userdata import UserDataError

from .conftest import CANDIDATE_SYSTEM, PIPELINE, add_posting
from .fakes import FakeLLM, label_lines, skill
from .test_userdata import JOB, OTHER, T1, all_rows, write


@pytest.fixture
def db(engine):
    add_posting(engine)
    add_posting(engine, "senior-ai-engineer.json")
    write(engine, userdata.set_setting, "llm.model", "gemma4:12b")
    return engine


def good_llm(**kwargs):
    """Answers for the search_results posting: two required lines, one skill each."""
    return FakeLLM(
        {
            "lines": [label_lines({"data lineage": "required", "data governance": "required"})],
            "skills": [
                {"skills": [skill(1, "Data lineage", "data lineage"), skill(2, "Data governance", "data governance")]}
            ],
        },
        **kwargs,
    )


def job_rows(engine):
    with engine.connect() as conn:
        return conn.execute(select(llm_jobs).order_by(llm_jobs.c.id)).all()


def enqueue(engine, job_id=JOB):
    return write(engine, jobs.enqueue, job_id)


# --- Enqueueing (6.2) ---


def test_enqueue_records_snapshot_model_and_pipeline(db):
    job_id, added = enqueue(db)
    [job] = job_rows(db)
    assert added and job.id == job_id
    assert (job.job_id, job.model, job.pipeline, job.status) == (JOB, "gemma4:12b", PIPELINE, "queued")
    with db.connect() as conn:
        from jobhunt.store import latest_snapshot

        assert job.snapshot_id == latest_snapshot(conn, JOB).id


def test_enqueue_deduplicates(db):
    first, _ = enqueue(db)
    again, added = enqueue(db)
    assert again == first and not added
    assert len(job_rows(db)) == 1


def test_settings_change_leaves_queued_work(db):
    enqueue(db)
    write(db, userdata.set_setting, "llm.model", "phi4:latest")
    write(db, userdata.set_setting, "llm.segmenter", "rules")
    assert job_rows(db)[0].model == "gemma4:12b" and job_rows(db)[0].pipeline == PIPELINE


def test_enqueue_needs_a_model(engine):
    add_posting(engine)
    with pytest.raises(UserDataError, match="model"):
        enqueue(engine)


def test_enqueue_unextracted(db):
    assert write(db, jobs.enqueue_unextracted, ListFilters()) == 2
    assert write(db, jobs.enqueue_unextracted, ListFilters()) == 0
    assert {j.job_id for j in job_rows(db)} == {JOB, OTHER}


# --- run_next (6.2) ---


def test_run_next_done(db):
    enqueue(db)
    llm = good_llm()
    assert jobs.run_next(db, llm) == "done"
    [job] = job_rows(db)
    [run] = all_rows(db, posting_enrichments)
    assert (job.status, job.enrichment_id, run.status, run.model, run.pipeline) == (
        "done",
        run.id,
        "succeeded",
        "gemma4:12b",
        PIPELINE,
    )
    assert run.origin == "app"
    assert job.started_at is not None and job.finished_at is not None
    assert llm.model == "gemma4:12b" and llm.num_ctx == 8192
    assert jobs.run_next(db, llm) is None


def test_queued_job_naming_a_removed_version(db):
    removed = PIPELINE.replace("skills=atomic@2", "skills=atomic@4")
    write(db, jobs.enqueue, JOB, model="gemma4:12b", pipeline=removed)
    enqueue(db, OTHER)
    llm = good_llm()
    assert jobs.run_next(db, llm) == "failed"
    assert removed in job_rows(db)[0].error and llm.requests == []
    assert all_rows(db, posting_enrichments) == []
    assert jobs.run_next(db, llm) in ("done", "failed") and job_rows(db)[1].status != "queued"  # later jobs run


def test_extraction_uses_the_apps_skill_method(db, candidate):
    with db.begin() as conn:  # a stray setting from an earlier version of the app is ignored
        conn.execute(app_settings.insert().values(key="llm.skills", value="atomic@5", updated_at=T1))
    with db.connect() as conn:
        assert jobs.current_pipeline(conn) == ("gemma4:12b", PIPELINE)
    enqueue(db)
    llm = good_llm()
    assert jobs.run_next(db, llm) == "done"
    [run] = all_rows(db, posting_enrichments)
    assert run.pipeline == PIPELINE and run.origin == "app"
    assert all(r.system != CANDIDATE_SYSTEM for r in llm.requests if r.key == "skills")


def test_run_next_failed(db):
    enqueue(db)
    llm = good_llm()
    llm.responses["skills"] = [{"skills": []}]
    assert jobs.run_next(db, llm) == "failed"
    [job] = job_rows(db)
    [run] = all_rows(db, posting_enrichments)
    assert job.error == run.error == "skills: no skills were extracted from the required lines"
    assert run.status == "failed" and job.enrichment_id == run.id


def test_run_next_cancelled_mid_run(db):
    enqueue(db)
    enqueue(db, OTHER)

    def cancel_on_first_call(key):
        if key == "lines":
            write(db, jobs.cancel_all)

    llm = good_llm(on_call=cancel_on_first_call)
    assert jobs.run_next(db, llm) == "cancelled"
    assert [(j.status, j.finished_at is not None) for j in job_rows(db)] == [("cancelled", True), ("cancelled", True)]
    assert llm.calls("skills") == 0 and all_rows(db, posting_enrichments) == []
    assert jobs.run_next(db, llm) is None  # the queued job was cancelled too: no model requests


def test_cancel_queued_makes_no_requests(db):
    enqueue(db)
    enqueue(db, OTHER)
    assert write(db, jobs.cancel_all) == 2
    llm = good_llm()
    assert jobs.run_next(db, llm) is None
    assert llm.requests == []
    assert [j.status for j in job_rows(db)] == ["cancelled", "cancelled"]


def test_unreachable_requeues(db):
    enqueue(db)
    with pytest.raises(Unreachable):
        jobs.run_next(db, FakeLLM(unreachable=True))
    [job] = job_rows(db)
    assert (job.status, job.started_at) == ("queued", None)
    assert jobs.run_next(db, good_llm()) == "done"


def test_recover_requeues_running_jobs(db):
    enqueue(db)
    enqueue(db, OTHER)
    jobs._claim(db)  # serve stopped while this one was running
    assert [j.status for j in job_rows(db)] == ["running", "queued"]
    jobs.recover(db)
    assert [j.status for j in job_rows(db)] == ["queued", "queued"]


def test_unavailable_pipeline_fails_the_job(db):
    write(db, jobs.enqueue, JOB, "gemma4:12b", "seg=gone@1 skills=atomic@1 salary=paylines@1 validate=v@1")
    assert jobs.run_next(db, good_llm()) == "failed"
    assert "not available" in job_rows(db)[0].error


def test_no_model_call_inside_a_transaction(db):
    open_transactions = []
    event.listen(db, "begin", lambda conn: open_transactions.append(1))
    event.listen(db, "commit", lambda conn: open_transactions.pop())
    event.listen(db, "rollback", lambda conn: open_transactions.pop())

    def no_transaction(key):
        assert open_transactions == [], f"model call for {key!r} inside a transaction"

    enqueue(db)
    llm = good_llm(on_call=no_transaction)
    assert jobs.run_next(db, llm) == "done"
    assert llm.calls("lines") == 1 and llm.calls("skills") == 1


# --- Worker (6.3) ---


def test_worker_processes_queued_jobs(db):
    worker = jobs.Worker(db, good_llm(), idle_wait=0.05, offline_backoff=0.05)
    worker.start()
    try:
        enqueue(db)
        enqueue(db, OTHER)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(j.status in ("queued", "running") for j in job_rows(db)):
            time.sleep(0.02)
    finally:
        worker.stop()
        worker.join(5)
    assert not worker.is_alive()
    statuses = [j.status for j in job_rows(db)]
    assert statuses[0] == "done" and statuses[1] in ("done", "failed")  # OTHER has no required lines to match


def test_worker_waits_while_offline_and_recovers_at_start(db):
    enqueue(db)
    jobs._claim(db)
    llm = FakeLLM(unreachable=True)
    worker = jobs.Worker(db, llm, idle_wait=0.05, offline_backoff=0.05)
    worker.start()
    time.sleep(0.3)
    worker.stop()
    worker.join(5)
    assert [j.status for j in job_rows(db)] == ["queued"]
    assert llm.requests == []
