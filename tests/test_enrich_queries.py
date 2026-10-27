"""Read models for model output: the detail panel, list salary summary, labelled filter, counts and queue."""

import pytest

from jobhunt import queries, userdata
from jobhunt.enrich import jobs
from jobhunt.enrich.pipeline import SalaryItem
from jobhunt.queries import ListFilters

from .conftest import PIPELINE, add_posting, add_run
from .test_userdata import JOB, OTHER, T2, write

PAY = "Salary: $2,950.40 - $3,610.00 Bi-Weekly"
PAY_JOB = 3  # the third posting the db fixture imports


@pytest.fixture
def db(engine):
    add_posting(engine)
    add_posting(engine, "senior-ai-engineer.json")
    assert add_posting(engine, "health-economist.json") == PAY_JOB
    return engine


def read(engine, fn, *args, **kwargs):
    with engine.connect() as conn:
        return fn(conn, *args, **kwargs)


def pay(lo, hi, quote, currency="USD", period="biweekly"):
    return SalaryItem(lo, hi, currency, period, None, "base", quote)


# --- enrichment_panel (7.1) ---


def test_panel_none_without_runs(db):
    assert read(db, queries.enrichment_panel, JOB) is None


def test_panel_latest_run_items_and_flags(db):
    old = add_run(db, skills=[("Data lineage", "required", "data lineage")], model="phi4:latest")
    latest = add_run(
        db,
        skills=[
            ("Data lineage", "required", "data lineage"),
            ("Data governance", "required", "data governance"),
            ("LangChain", "preferred", "LangChain"),
            ("Communication", "preferred", "data automation"),
            ("Kubernetes", "required", "Kubernetes"),
        ],
    )
    write(db, userdata.add_skill_mark, JOB, "data lineage", "data lineage")
    write(db, userdata.reject_suggestion, JOB, "communication", "not-a-skill")
    panel = read(db, queries.enrichment_panel, JOB)
    assert panel["run"]["id"] == latest and [r["id"] for r in panel["runs"]] == [latest, old]
    assert not panel["stale"] and panel["acceptable"]
    required = [(s["name"], s["marked"]) for s in panel["skills"]["required"]]
    assert required == [("Data lineage", True), ("Data governance", False)]
    assert [s["name"] for s in panel["skills"]["preferred"]] == ["LangChain"]
    assert [s["name"] for s in panel["rejected"]] == ["Communication"]
    assert [s["name"] for s in panel["unverified_skills"]] == ["Kubernetes"]

    chosen = read(db, queries.enrichment_panel, JOB, old)
    assert chosen["run"]["model"] == "phi4:latest"
    assert read(db, queries.enrichment_panel, JOB, 99999)["run"]["id"] == latest  # unknown run: the latest


def test_panel_failed_and_stale_runs(db):
    add_run(db, status="failed", error="segment: Ollama returned HTTP 500")
    add_posting(db, tag="v2", captured_at=T2, description_text="Rewritten.", description_html="<p>Rewritten.</p>")
    panel = read(db, queries.enrichment_panel, JOB)
    assert panel["run"]["error"] == "segment: Ollama returned HTTP 500"
    assert panel["stale"] and not panel["acceptable"]


def test_panel_only_eval_runs(db):
    add_run(db, skills=[("Data lineage", "required", "data lineage")], origin="eval")
    assert read(db, queries.enrichment_panel, JOB) is None


def test_eval_run_stays_out_of_the_app(db):
    app = add_run(
        db, PAY_JOB, skills=[("Payroll", "required", "Salary")], salaries=[pay(2950.4, 3610, "$2,950.40 - $3,610.00")]
    )
    candidate = PIPELINE.replace("skills=atomic@2", "skills=atomic@5")
    evaluated = add_run(
        db, PAY_JOB, skills=[("Bi-weekly pay", "required", "Bi-Weekly")], salaries=[pay(3610, None, "$3,610.00")],
        pipeline=candidate, origin="eval",
    )
    panel = read(db, queries.enrichment_panel, PAY_JOB)
    assert panel["run"]["id"] == app and [r["id"] for r in panel["runs"]] == [app]
    assert read(db, queries.enrichment_panel, PAY_JOB, evaluated)["run"]["id"] == app  # not selectable
    assert [s["name"] for s in read(db, queries.posting_skills, PAY_JOB)] == ["Payroll"]
    summary = rows_by_job(db)[PAY_JOB]["salary"]
    assert (summary["min_amount"], summary["max_amount"]) == (2950.4, 3610)


def test_panel_salaries(db):
    add_run(db, PAY_JOB, salaries=[pay(2950.4, 3610, "$2,950.40 - $3,610.00"), pay(1, 2, "$2,950.40")])
    panel = read(db, queries.enrichment_panel, PAY_JOB)
    assert [(s["min_amount"], s["max_amount"]) for s in panel["salaries"]] == [(2950.4, 3610)]
    assert len(panel["unverified_salaries"]) == 1


# --- List salary summary and labelled filter (7.2) ---


def rows_by_job(engine, filters=ListFilters()):
    return {r["job_id"]: r for r in read(engine, queries.posting_list, filters)}


def test_salary_summary_from_latest_successful_run(db):
    add_run(db, PAY_JOB, salaries=[pay(1000, 2000, "$2,950.40")])  # older, unverified
    add_run(
        db,
        PAY_JOB,
        salaries=[pay(2950.4, 3610, "$2,950.40 - $3,610.00"), pay(1, 1, "nope"), pay(3610, None, "$3,610.00")],
    )
    add_run(db, PAY_JOB, status="failed", error="salary: broken")  # failed runs don't count
    rows = rows_by_job(db)
    summary = rows[PAY_JOB]["salary"]
    assert (summary["min_amount"], summary["max_amount"], summary["currency"]) == (2950.4, 3610, "USD")
    assert rows[PAY_JOB]["salary_more"] == 1
    assert rows[JOB]["salary"] is None and rows[JOB]["salary_more"] == 0


def test_no_salary_from_an_eval_run(db):
    add_run(db, PAY_JOB, salaries=[pay(2950.4, 3610, "$2,950.40 - $3,610.00")], origin="eval")
    assert rows_by_job(db)[PAY_JOB]["salary"] is None


def test_no_salary_for_run_on_older_snapshot(db):
    add_run(db, PAY_JOB, salaries=[pay(2950.4, 3610, "$2,950.40 - $3,610.00")])
    add_posting(db, "health-economist.json", tag="v2", captured_at=T2, description_text=PAY + " (updated)")
    assert rows_by_job(db)[PAY_JOB]["salary"] is None


def test_labelled_filter(db):
    write(db, userdata.set_skills_complete, JOB, True)
    assert set(rows_by_job(db, ListFilters(labelled="yes"))) == {JOB}
    assert set(rows_by_job(db, ListFilters(labelled="no"))) == {OTHER, PAY_JOB}
    write(db, userdata.set_skills_complete, JOB, False)
    assert set(rows_by_job(db, ListFilters(labelled="yes"))) == set()


def test_labelled_filter_url_round_trip():
    filters = ListFilters.from_args({"labelled": "yes", "q": "ml"})
    assert filters.labelled == "yes"
    assert ListFilters.from_args(filters.to_args()) == filters
    assert ListFilters.from_args({"labelled": "maybe"}).labelled == ""
    assert "labelled" not in ListFilters().to_args()


# --- Unextracted count and queue overview (7.3) ---


def test_unextracted_count_matches_what_is_queued(db):
    write(db, userdata.set_setting, "llm.model", "gemma4:12b")
    reason = read(db, lambda c: userdata.add_dismiss_reason(c, "Other").id)
    write(db, userdata.dismiss, OTHER, [reason])
    add_run(db, JOB)  # already extracted with the current model and pipeline
    add_run(db, PAY_JOB, model="phi4:latest")  # another model doesn't count
    count = read(db, queries.unextracted_count, ListFilters(dismissed="included"), "gemma4:12b", PIPELINE)
    assert count == 1
    assert write(db, jobs.enqueue_unextracted, ListFilters(dismissed="included")) == count
    assert read(db, queries.unextracted_count, ListFilters(), "gemma4:12b", PIPELINE) == 0  # now queued


def test_eval_run_does_not_count_as_extracted(db):
    write(db, userdata.set_setting, "llm.model", "gemma4:12b")
    add_run(db, JOB, origin="eval")  # current model and pipeline, but made by jobhunt eval
    add_run(db, OTHER)
    assert set(read(db, queries.unextracted_ids, ListFilters(), "gemma4:12b", PIPELINE)) == {JOB, PAY_JOB}
    assert write(db, jobs.enqueue_unextracted, ListFilters()) == 2


def test_unextracted_count_follows_filters_and_model(db):
    assert read(db, queries.unextracted_count, ListFilters(q="research lab"), "gemma4:12b", PIPELINE) == 0
    assert read(db, queries.unextracted_count, ListFilters(), "gemma4:12b", PIPELINE) == 3
    assert read(db, queries.unextracted_count, ListFilters(), None, PIPELINE) == 0


def test_queue_overview(db):
    write(db, userdata.set_setting, "llm.model", "gemma4:12b")
    for job_id in (JOB, OTHER, PAY_JOB):
        write(db, jobs.enqueue, job_id)
    jobs._claim(db)
    overview = read(db, queries.queue_overview)
    assert [(j["job_id"], j["status"]) for j in overview["active"]] == [
        (JOB, "running"),
        (OTHER, "queued"),
        (PAY_JOB, "queued"),
    ]
    assert overview["busy"] and (overview["running"], overview["queued"]) == (1, 2)
    assert overview["active"][0]["title"]

    write(db, jobs.cancel_all)
    overview = read(db, queries.queue_overview)
    assert overview["active"] == [] and overview["busy"]  # the running job is still cancelling
    assert [j["cancelling"] for j in overview["recent"]] == [False, False, True]
    jobs.recover(db)
    assert not read(db, queries.queue_overview)["busy"]
    assert read(db, queries.posting_job, JOB)["status"] == "cancelled"
