"""OpenTelemetry spans of model work (model-tracing): the helpers, posting, document and links runs through the
queue, the evaluations, the ids stored results keep, what spans never hold, and the options that turn it on.

Skipped as a module without the otel extra; tests/test_tracing_off.py covers tracing off."""

import json

import pytest
from sqlalchemy import select

from jobhunt import userdata
from jobhunt.cli import main
from jobhunt.db import (
    app_settings,
    document_runs,
    enrichment_skills,
    link_judgments,
    link_measurements,
    llm_jobs,
    posting_enrichments,
    skill_expansions,
)
from jobhunt.enrich import evaluate, expand, jobs, links, tracing
from jobhunt.enrich.pipeline import Cancelled, StepFailed, Unreachable, run_pipeline, steps_for

from .conftest import PIPELINE, _tracing_into_memory, add_posting, get, post
from .fakes import FakeLLM, FakeOllama, label_lines, skill
from .test_cv_pipeline import CV_TEXT, ENTRIES, SKILLS, cv_skills_for, label_cv_lines
from .test_evaluate import TEXT as EVAL_TEXT
from .test_evaluate import eval_llm
from .test_evaluate import label as label_for_eval
from .test_link_eval import client as link_client
from .test_link_eval import labelled, links_db, measure, use_client  # noqa: F401  (fixtures)
from .test_links import AI, BANK, EMBED, db, mark, profile  # noqa: F401  (fixture)
from .test_profile_jobs import add_cv
from .test_userdata import all_rows, write
from .test_web_llm import make_client

pytest.importorskip("opentelemetry.sdk", reason="the otel extra isn't installed")

from opentelemetry.trace import SpanKind, StatusCode  # noqa: E402  (after the skip)

MODEL = "gemma4:12b"


# --- Reading the exported spans ---


def finished(exporter):
    return sorted(exporter.get_finished_spans(), key=lambda s: s.start_time)


def tree(exporter, under=None):
    """[(name, [children...])] in start order, from the roots (or under the span `under`)."""
    spans = finished(exporter)

    def kids(parent_id):
        return [s for s in spans if (s.parent.span_id if s.parent else None) == parent_id]

    def build(span):
        return (span.name, [build(k) for k in kids(span.context.span_id)])

    return [build(s) for s in kids(under.context.span_id if under else None)]


def named(exporter, name):
    return [s for s in finished(exporter) if s.name == name]


def one(exporter, name):
    [span] = named(exporter, name)
    return span


def ids_of(span):
    return {"trace_id": format(span.context.trace_id, "032x"), "span_id": format(span.context.span_id, "016x")}


def span_strings(exporter):
    """Every name, attribute value, status description and event of the exported spans, as text."""
    out = []
    for s in exporter.get_finished_spans():
        out.append(s.name)
        out += [str(v) for v in s.attributes.values()]
        if s.status.description:
            out.append(s.status.description)
        for event in s.events:
            out.append(event.name)
            out += [str(v) for v in event.attributes.values()]
    return out


def strings_in(value):
    """Every text inside a JSON-like value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in strings_in(v)]
    if isinstance(value, list):
        return [t for v in value for t in strings_in(v)]
    return []


def good_llm(**kwargs):
    """Answers for the bank posting (data-automation): two required lines, one skill each."""
    return FakeOllama(
        responses={
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


def run_all(engine, client):
    statuses = []
    while (status := jobs.run_next(engine, client)) is not None:
        statuses.append(status)
    return statuses


def queue_posting(engine, job_id=BANK):
    return write(engine, jobs.enqueue, job_id)[0]


# --- The helpers (1.4) ---


def test_helpers_build_the_tree_with_their_attributes(traced):
    llm = FakeLLM({"lines": [{"lines": []}]}).for_model(MODEL, 4096)
    with tracing.root("eval skills"):
        with tracing.run("posting", origin="eval", posting_id=4, snapshot_id=9, model=MODEL, pipeline=PIPELINE) as run:
            with tracing.step("segment", "llm-lines@2"):
                assert tracing.chat(llm, "system", "user", {"required": ["lines"]}) == {"lines": []}
            with tracing.step("embed", EMBED):
                assert len(tracing.embed(FakeOllama(), EMBED, ["Python", "SQL"])) == 2
            run.finish("succeeded")
    assert tree(traced) == [("eval skills", [("run posting", [
        ("step segment", [(f"chat {MODEL}", [])]), ("step embed", [(f"embeddings {EMBED}", [])]),
    ])])]
    run_span, step, chat, embed = (one(traced, n) for n in ("run posting", "step segment", f"chat {MODEL}",
                                                            f"embeddings {EMBED}"))
    assert (one(traced, "eval skills").kind, run_span.kind, step.kind) == (SpanKind.INTERNAL,) * 3
    assert chat.kind == embed.kind == SpanKind.CLIENT
    assert dict(run_span.attributes) == {
        "jobhunt.run.kind": "posting", "jobhunt.run.origin": "eval", "jobhunt.posting.id": 4,
        "jobhunt.snapshot.id": 9, "gen_ai.request.model": MODEL, "jobhunt.pipeline": PIPELINE,
        "jobhunt.run.status": "succeeded",
    }
    assert run_span.status.status_code == StatusCode.UNSET
    assert dict(step.attributes) == {"jobhunt.step.name": "segment", "jobhunt.step.method": "llm-lines@2"}
    assert dict(chat.attributes) == {
        "gen_ai.operation.name": "chat", "gen_ai.provider.name": "ollama", "gen_ai.request.model": MODEL,
        "gen_ai.request.temperature": 0, "gen_ai.request.seed": 7, "jobhunt.request.num_ctx": 4096,
    }
    assert dict(embed.attributes) == {
        "gen_ai.operation.name": "embeddings", "gen_ai.provider.name": "ollama", "gen_ai.request.model": EMBED,
        "jobhunt.embed.texts": 2,
    }


def test_a_failure_names_its_kind_without_its_message(traced):
    with pytest.raises(StepFailed), tracing.run("posting", origin="app"), tracing.step("skills", "atomic@2"):
        raise StepFailed("skills", "the answer quoted Example Robotics")
    for span in finished(traced):
        assert span.status.status_code == StatusCode.ERROR and span.status.description is None
        assert span.attributes["error.type"] == "StepFailed" and span.events == ()
    assert one(traced, "run posting").attributes["jobhunt.run.status"] == "failed"


@pytest.mark.parametrize(("error", "status"), [(Cancelled(), "cancelled"), (Unreachable("refused"), None)])
def test_cancelled_and_unreachable_runs(traced, error, status):
    with pytest.raises(type(error)), tracing.run("posting", origin="app"):
        raise error
    span = one(traced, "run posting")
    assert span.attributes.get("jobhunt.run.status") == status
    assert span.attributes["error.type"] == type(error).__name__ and span.status.status_code == StatusCode.ERROR


def test_a_run_finished_as_failed(traced):
    with tracing.run("posting", origin="app") as run:
        run.finish("failed", "skills: no skills were extracted from the required lines")
    span = one(traced, "run posting")
    assert span.attributes["jobhunt.run.status"] == "failed" and span.attributes["error.type"] == "StepFailed"
    assert span.status.description is None


def test_run_handles_refuse_unknown_attributes(traced):
    with pytest.raises(KeyError), tracing.run("posting", origin="app") as run:
        run.set(title="Senior engineer")


def test_ids_name_the_current_span(traced):
    assert tracing.ids() is None  # no span yet
    with tracing.run("links", origin="app"):
        current = tracing.ids()
    assert current == ids_of(one(traced, "run links"))
    assert tracing.with_ids({"a": 1}) == {"a": 1}


# --- Model calls (2.1) ---


def test_one_chat_span_per_request_including_the_retry(db, traced):
    queue_posting(db)
    client = good_llm()
    client.responses["skills"] = [{"skills": []}, {"skills": [skill(1, "Data lineage", "data lineage")]}]
    assert jobs.run_next(db, client) == "done"
    skills_step = one(traced, "step skills")
    assert [n for n, _ in tree(traced, skills_step)] == [f"chat {MODEL}"] * 2 == [f"chat {MODEL}"] * client.calls(
        "skills"
    )
    assert len(named(traced, f"chat {MODEL}")) == len(client.requests)


def test_tracing_changes_no_request(db):
    from jobhunt.store import latest_snapshot

    with db.connect() as conn:
        text = latest_snapshot(conn, BANK).description_text
    steps = steps_for("llm-lines")
    off = good_llm().for_model(MODEL, 8192)
    untraced = run_pipeline(text, off, steps)
    with _tracing_into_memory(False):
        on = good_llm().for_model(MODEL, 8192)
        traced_run = run_pipeline(text, on, steps)
    assert off.requests == on.requests and off.requests

    def timeless(value):
        if isinstance(value, dict):
            return {k: timeless(v) for k, v in value.items() if k not in ("seconds", "otel")}
        if isinstance(value, list):
            return [timeless(v) for v in value]
        return value

    assert "otel" not in untraced.trace and "otel" not in json.dumps(untraced.trace)
    assert timeless(untraced.trace) == timeless(traced_run.trace)
    assert [c.item for c in untraced.skills] == [c.item for c in traced_run.skills]


# --- Runs and steps through the queue (3.1, 3.3) ---


def test_posting_job_trace(db, traced):
    job_id = queue_posting(db)
    assert jobs.run_next(db, good_llm()) == "done"
    run_span = one(traced, "run posting")
    assert [n for n, _ in tree(traced, run_span)] == ["step segment", "step skills", "step salary"]
    methods = [one(traced, f"step {n}").attributes["jobhunt.step.method"] for n in ("segment", "skills", "salary")]
    assert methods == ["llm-lines@2", "atomic@2", "paylines@1"]
    [run] = all_rows(db, posting_enrichments)
    [job] = job_rows(db)
    assert dict(run_span.attributes) == {
        "jobhunt.run.kind": "posting", "jobhunt.run.origin": "app", "jobhunt.job.id": job_id,
        "jobhunt.posting.id": BANK, "jobhunt.snapshot.id": job.snapshot_id, "gen_ai.request.model": MODEL,
        "jobhunt.pipeline": PIPELINE, "jobhunt.run.id": run.id, "jobhunt.run.status": "succeeded",
    }
    assert json.loads(run.output_json)["otel"] == ids_of(run_span)
    assert list(json.loads(run.output_json))[-1] == "otel"  # added last


def test_failed_posting_job(db, traced):
    queue_posting(db)
    client = good_llm()
    client.responses["skills"] = [{"skills": []}]
    assert jobs.run_next(db, client) == "failed"
    run_span, skills_step = one(traced, "run posting"), one(traced, "step skills")
    assert run_span.attributes["jobhunt.run.status"] == "failed"
    for span in (run_span, skills_step):
        assert span.status.status_code == StatusCode.ERROR and span.attributes["error.type"] == "StepFailed"
    assert one(traced, "step segment").status.status_code == StatusCode.UNSET
    [run] = all_rows(db, posting_enrichments)
    assert run.status == "failed" and json.loads(run.output_json)["otel"] == ids_of(run_span)


def test_not_json_answer_fails_the_chat_step_and_run(db, traced):
    queue_posting(db)

    def not_json(user):
        raise StepFailed(None, "the model's answer is not valid JSON")

    client = good_llm()
    client.responses["skills"] = [not_json]
    assert jobs.run_next(db, client) == "failed"
    skills_step = one(traced, "step skills")
    [chat] = [s for s in named(traced, f"chat {MODEL}") if s.parent.span_id == skills_step.context.span_id]
    for span in (chat, skills_step, one(traced, "run posting")):
        assert span.status.status_code == StatusCode.ERROR and span.attributes["error.type"] == "StepFailed"
    assert one(traced, "run posting").attributes["jobhunt.run.status"] == "failed"


def test_cancelled_posting_job_holds_the_segment_step_only(db, traced):
    queue_posting(db)

    def cancel_on_first_call(key):
        if key == "lines":
            write(db, jobs.cancel_all)

    assert jobs.run_next(db, good_llm(on_call=cancel_on_first_call)) == "cancelled"
    run_span = one(traced, "run posting")
    assert [n for n, _ in tree(traced, run_span)] == ["step segment"]
    assert run_span.attributes["jobhunt.run.status"] == "cancelled"
    assert run_span.attributes["error.type"] == "Cancelled"
    assert all_rows(db, posting_enrichments) == []


def test_unreachable_posting_job(db, traced):
    queue_posting(db)
    with pytest.raises(Unreachable):
        jobs.run_next(db, FakeOllama(state="offline"))
    run_span = one(traced, "run posting")
    assert "jobhunt.run.status" not in run_span.attributes and run_span.attributes["error.type"] == "Unreachable"
    assert [j.status for j in job_rows(db)] == ["queued"]


def test_traced_job_stores_what_an_untraced_one_does(db, traced):
    queue_posting(db)
    assert jobs.run_next(db, good_llm()) == "done"
    tracing.reset()
    queue_posting(db)
    assert jobs.run_next(db, good_llm()) == "done"
    first, second = all_rows(db, posting_enrichments)
    assert (first.status, first.error, first.model, first.pipeline, first.origin) == (
        second.status, second.error, second.model, second.pipeline, second.origin
    )
    with db.connect() as conn:
        def items(run_id):
            return [
                (r.position, r.name, r.importance, r.quote, r.start_offset, r.end_offset, r.verified)
                for r in conn.execute(select(enrichment_skills).where(enrichment_skills.c.enrichment_id == run_id))
            ]

        assert items(first.id) == items(second.id) != []
    assert "otel" in json.loads(first.output_json) and "otel" not in json.loads(second.output_json)
    assert [(j.status, j.error) for j in job_rows(db)] == [("done", None), ("done", None)]


# --- Document runs (3.2) ---


def document_client(**kwargs):
    return FakeOllama(responses={"lines": [label_cv_lines(ENTRIES)], "cv_skills": [cv_skills_for(SKILLS)]}, **kwargs)


def test_document_job_trace(db, traced):
    document_id = add_cv(db)
    job_id = write(db, jobs.enqueue_document, document_id)[0]
    client = document_client()
    assert jobs.run_next(db, client) == "done"
    run_span = one(traced, "run document")
    steps = tree(traced, run_span)
    assert [n for n, _ in steps] == ["step sections", "step lines", "step records", "step skills", "step part_of"]
    calls = dict(steps)
    assert calls["step sections"] == calls["step records"] == []
    for name in ("step lines", "step skills", "step part_of"):
        assert calls[name] and all(c == (f"chat {MODEL}", []) for c in calls[name])
    assert sum(len(c) for c in calls.values()) == len(client.requests)
    ended = [one(traced, n) for n, _ in steps]
    assert all(a.end_time <= b.start_time for a, b in zip(ended, ended[1:], strict=False))
    [run] = all_rows(db, document_runs)
    assert dict(run_span.attributes) == {
        "jobhunt.run.kind": "document", "jobhunt.run.origin": "app", "jobhunt.job.id": job_id,
        "jobhunt.document.id": document_id, "gen_ai.request.model": MODEL, "jobhunt.pipeline": run.pipeline,
        "jobhunt.run.id": run.id, "jobhunt.run.status": "succeeded",
    }
    assert json.loads(run.output_json)["otel"] == ids_of(run_span)


# --- Links jobs (3.4) ---


def test_links_job_trace(db, traced):
    mark(db, AI, "Python scripting", "Python")  # shortlisted: close to the profile's "Python scripts"
    mark(db, AI, "Salesforce", "Salesforce")  # nothing close: judged without a request
    profile(db, "Python scripts")
    client = FakeOllama(
        responses={"relations": [{"relations": [{"candidate": 1, "relation": "same"}]}]},
        vectors={"Python scripting": [1.0, 0.0], "Python scripts": [1.0, 0.1], "Salesforce": [0.0, 1.0]},
    )
    assert run_all(db, client) == ["done"]
    run_span = one(traced, "run links")
    assert tree(traced, run_span) == [
        ("step embed", [(f"embeddings {EMBED}", [])]),
        ("step judge", [(f"chat {MODEL}", [])]),
    ]
    embedded = one(traced, f"embeddings {EMBED}")
    assert embedded.attributes["jobhunt.embed.texts"] == len(client.embed_requests[0][1]) == 3
    assert one(traced, "step judge").attributes["jobhunt.step.method"] == links.CURRENT_JUDGE
    assert one(traced, "step embed").attributes["jobhunt.step.method"] == EMBED
    [job] = job_rows(db)
    assert dict(run_span.attributes) == {
        "jobhunt.run.kind": "links", "jobhunt.run.origin": "app", "jobhunt.job.id": job.id,
        "gen_ai.request.model": MODEL, "jobhunt.pipeline": links.PIPELINE, "jobhunt.embed_model": EMBED,
        "jobhunt.links.planned": 2, "jobhunt.links.judged": 2, "jobhunt.links.failed": 0,
        "jobhunt.run.status": "succeeded",
    }
    outputs = {j.posting_key: json.loads(j.output_json) for j in all_rows(db, link_judgments)}
    assert outputs["python scripting"]["otel"] == ids_of(one(traced, "step judge"))
    assert outputs["salesforce"]["otel"] == ids_of(run_span)


def test_failed_judgment_marks_its_step(db, traced, monkeypatch):
    monkeypatch.setattr(links, "SHORTLIST_FLOOR", -1.0)
    mark(db, AI, "Python scripting", "Python")
    profile(db, "Python")
    assert run_all(db, FakeOllama(responses={"relations": [{"relations": [{"candidate": "one"}]}]})) == ["done"]
    judge_step = one(traced, "step judge")
    assert judge_step.status.status_code == StatusCode.ERROR and judge_step.attributes["error.type"] == "StepFailed"
    assert one(traced, "run links").attributes["jobhunt.links.failed"] == 1


def test_embedding_failure_fails_the_links_run(db, traced):
    mark(db, AI, "Python scripting", "Python")
    profile(db, "Python")
    client = FakeOllama()
    client.embed_failure = "asked for 2 embeddings and got 1"
    assert run_all(db, client) == ["failed"]
    for name in ("run links", "step embed", f"embeddings {EMBED}"):
        assert one(traced, name).status.status_code == StatusCode.ERROR
    assert one(traced, "run links").attributes["jobhunt.run.status"] == "failed"


def test_expansion_pass_is_one_step(db, traced):
    wanted = [expand.Wanted("posting", "python", "Python", "Python"), expand.Wanted("profile", "sql", "SQL", None)]
    llm = FakeLLM({"phrases": [{"phrases": ["Python programming"]}]}).for_model(MODEL, 8192)
    expand.expand_all(db, llm, MODEL, wanted)
    step = one(traced, "step expand")
    assert step.attributes["jobhunt.step.method"] == expand.STEP
    assert tree(traced) == [("step expand", [(f"chat {MODEL}", []), (f"chat {MODEL}", [])])]
    assert [json.loads(r.output_json)["otel"] for r in all_rows(db, skill_expansions)] == [ids_of(step)] * 2


# --- Evaluations (3.5) ---


@pytest.fixture
def eval_db(engine):
    add_posting(engine, description_text=EVAL_TEXT, description_html="<p>" + EVAL_TEXT.replace("\n", "<br>") + "</p>")
    write(engine, userdata.set_setting, "llm.model", MODEL)
    label_for_eval(engine)
    return engine


def test_eval_run_spans_and_reuse(eval_db, traced):
    with tracing.root("eval skills"):
        evaluate.execute(eval_db, eval_llm(), evaluate.plan(eval_db))
    [root] = tree(traced)
    assert root[0] == "eval skills" and [n for n, _ in root[1]] == ["run posting"]
    run_span = one(traced, "run posting")
    assert run_span.attributes["jobhunt.run.origin"] == "eval" and "jobhunt.job.id" not in run_span.attributes
    assert one(traced, "step skills").attributes["jobhunt.step.method"] == "atomic@2"
    [run] = all_rows(eval_db, posting_enrichments)
    assert json.loads(run.output_json)["otel"] == ids_of(run_span)
    assert ids_of(run_span)["trace_id"] == ids_of(one(traced, "eval skills"))["trace_id"]
    traced.clear()
    with tracing.root("eval skills"):
        report = evaluate.execute(eval_db, eval_llm(), evaluate.plan(eval_db))
    assert report.reused_runs == 1 and tree(traced) == [("eval skills", [])]


def test_link_eval_spans_and_reuse(labelled, traced):
    engine, _ = labelled
    from .test_links import relations_answer

    c = link_client(relations_answer("specific", "related"))
    _, report = measure(engine, c)
    run_span = one(traced, "run links")
    assert run_span.attributes["jobhunt.run.origin"] == "eval"
    judges = named(traced, "step judge")
    assert len(judges) == report.new_judgments > 0
    assert all(j.parent.span_id == run_span.context.span_id for j in judges)
    assert all(one_chat.parent.span_id in {j.context.span_id for j in judges}
               for one_chat in named(traced, f"chat {MODEL}"))
    stored = [json.loads(m.output_json)["otel"] for m in all_rows(engine, link_measurements)]
    assert sorted(o["span_id"] for o in stored) == sorted(ids_of(j)["span_id"] for j in judges)
    traced.clear()
    _, again = measure(engine, link_client(relations_answer("specific", "related")))
    assert again.new_judgments == 0 and named(traced, "step judge") == [] and named(traced, "step embed") == []
    assert len(named(traced, "run links")) == 1


# --- Content (6.1, 6.2) ---


class Recording(FakeOllama):
    """FakeOllama keeping every answer it gave."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.answers = []

    def chat_json(self, system, user, schema):
        answer = super().chat_json(system, user, schema)
        self.answers.append(answer)
        return answer


def every_kind_of_job(engine, monkeypatch):
    """A posting job, a document job, a links job and a failed posting job; (client, failing client, error)."""
    monkeypatch.setattr(links, "SHORTLIST_FLOOR", -1.0)
    responses = {
        "lines": [lambda user: (label_lines({"data lineage": "required"}) if "data lineage" in user
                                else label_cv_lines(ENTRIES))(user)],
        "skills": [{"skills": [skill(1, "Data lineage", "data lineage")]}],
        "cv_skills": [cv_skills_for(SKILLS)],
        "relations": [{"relations": [{"candidate": 1, "relation": "related"}]}],
    }
    client = Recording(responses=responses)
    queue_posting(engine)
    write(engine, jobs.enqueue_document, add_cv(engine))
    profile(engine, "Lineage tracking")
    assert run_all(engine, client) == ["done", "done", "done"]
    failing = Recording(responses={**responses, "skills": [{"skills": []}]})
    queue_posting(engine)
    assert run_all(engine, failing) == ["failed"]
    [failed] = [j for j in job_rows(engine) if j.status == "failed"]
    return client, failing, failed.error


def private_texts(engine, clients, error):
    from jobhunt.store import latest_snapshot

    with engine.connect() as conn:
        posting = latest_snapshot(conn, BANK).description_text
    texts = [*posting.splitlines(), *CV_TEXT.splitlines(), error, error.split(": ", 1)[1]]
    for c in clients:
        texts += [r.system for r in c.requests] + [r.user for r in c.requests]
        texts += [json.dumps(a) for a in c.answers] + [t for a in c.answers for t in strings_in(a)]
    names = [r.name for r in all_rows(engine, enrichment_skills)] + ["Lineage tracking", "Data lineage"]
    texts += names + [n.lower() for n in names]
    return {t.strip() for t in texts if len(t.strip()) >= 5}


def test_default_spans_hold_no_text(db, traced, monkeypatch):
    client, failing, error = every_kind_of_job(db, monkeypatch)
    strings = span_strings(traced)
    assert {s.name for s in finished(traced)} >= {"run posting", "run document", "run links", "step judge"}
    leaks = sorted({t for t in private_texts(db, [client, failing], error) for s in strings if t in s})
    assert leaks == []
    assert all(s.status.description is None and s.events == () for s in finished(traced))


def test_content_spans_carry_messages_answers_and_errors(db, traced_content, monkeypatch):
    client, failing, error = every_kind_of_job(db, monkeypatch)
    chats = named(traced_content, f"chat {MODEL}")
    requests = client.requests + failing.requests
    assert len(chats) == len(requests)
    for span, request, answer in zip(chats, requests, client.answers + failing.answers, strict=True):
        [instructions] = json.loads(span.attributes["gen_ai.system_instructions"])
        assert instructions == {"type": "text", "content": request.system}
        [message] = json.loads(span.attributes["gen_ai.input.messages"])
        assert message == {"role": "user", "parts": [{"type": "text", "content": request.user}]}
        [output] = json.loads(span.attributes["gen_ai.output.messages"])
        assert json.loads(output["parts"][0]["content"]) == answer and output["role"] == "assistant"
    assert one(traced_content, "step judge").attributes["jobhunt.link.posting_key"] == "data lineage"
    failed_runs = [s for s in named(traced_content, "run posting") if s.attributes["jobhunt.run.status"] == "failed"]
    assert [s.status.description for s in failed_runs] == [error]
    embedded = " ".join(t for _, texts in client.embed_requests for t in texts)
    for span in named(traced_content, f"embeddings {EMBED}"):
        assert set(span.attributes) == {
            "gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model", "jobhunt.embed.texts"
        }
    assert embedded  # there were texts, and none of them is on a span


def test_content_message_on_a_failed_step(traced_content):
    with pytest.raises(StepFailed), tracing.step("skills", "atomic@2"):
        raise StepFailed("skills", "the answer is not valid JSON")
    assert one(traced_content, "step skills").status.description == "the answer is not valid JSON"


# --- The posting page (5.1) ---


def test_posting_page_shows_the_runs_trace(db, tmp_path):
    ollama = FakeOllama()
    page = make_client(db, tmp_path, ollama)
    queue_posting(db)
    jobs.run_next(db, good_llm())
    html = get(page, f"/postings/{BANK}").get_data(as_text=True)
    assert "trace <code>" not in html  # made without tracing
    with _tracing_into_memory(False) as exporter:
        queue_posting(db)
        jobs.run_next(db, good_llm())
        trace_id = ids_of(one(exporter, "run posting"))["trace_id"]
    html = get(page, f"/postings/{BANK}").get_data(as_text=True)
    assert f'trace <code>{trace_id}</code>' in html
    first_run = all_rows(db, posting_enrichments)[0]
    older = get(page, f"/postings/{BANK}?run={first_run.id}").get_data(as_text=True)
    assert "trace <code>" not in older


# --- Not from the browser (4.3) ---


def test_settings_requests_cannot_set_tracing(db, tmp_path):
    page = make_client(db, tmp_path, FakeOllama())
    post(page, "/settings", {"model": MODEL, "num_ctx": "8192", "segmenter": "llm-lines",
                             "otlp_endpoint": "http://localhost:4318/v1/traces", "trace_content": "1"})
    with db.connect() as conn:
        keys = set(conn.execute(select(app_settings.c.key)).scalars())
    assert not any("otlp" in k or "trace" in k for k in keys)
    assert not tracing.enabled() and not tracing.content()


# --- The commands (4.2) ---


@pytest.fixture
def setup_into_memory(monkeypatch):
    """tracing.setup installs an in-memory exporter instead of an OTLP one; yields (exporter, setup calls)."""
    calls = []
    holder = {}

    def setup(endpoint, content=False):
        calls.append((endpoint, content))
        if endpoint is None:
            return lambda: None
        manager = _tracing_into_memory(content)
        holder["exporter"] = manager.__enter__()
        return lambda: manager.__exit__(None, None, None)

    monkeypatch.setattr(tracing, "setup", setup)
    return holder, calls


def test_eval_report_is_the_same_with_tracing(tmp_path, monkeypatch, capsys, setup_into_memory):
    from jobhunt.db import init_db, make_engine

    holder, calls = setup_into_memory
    url = f"sqlite:///{tmp_path / 'eval.db'}"
    engine = make_engine(url)
    init_db(engine)
    add_posting(engine, description_text=EVAL_TEXT, description_html="<p>" + EVAL_TEXT.replace("\n", "<br>") + "</p>")
    write(engine, userdata.set_setting, "llm.model", MODEL)
    label_for_eval(engine)
    engine.dispose()
    monkeypatch.setattr("jobhunt.enrich.ollama.OllamaClient", lambda url: eval_llm())
    assert main(["eval", "--db", url, "--fresh"]) == 0
    untraced = capsys.readouterr().out
    assert main(["eval", "--db", url, "--fresh", "--otlp-endpoint", "http://localhost:4318/v1/traces"]) == 0
    assert capsys.readouterr().out == untraced
    assert calls == [(None, False), ("http://localhost:4318/v1/traces", False)]
    exporter = holder["exporter"]
    [(root, runs)] = tree(exporter)
    assert root == "eval skills" and [n for n, _ in runs] == ["run posting"]


def test_eval_links_root_holds_the_measurement(links_db, monkeypatch, capsys, setup_into_memory):
    from .test_links import relations_answer

    holder, _ = setup_into_memory
    use_client(monkeypatch, link_client(relations_answer("specific")))
    assert main(["eval", "--links", "--db", links_db, "--fresh"]) == 0
    untraced = capsys.readouterr().out
    use_client(monkeypatch, link_client(relations_answer("specific")))
    assert main(["eval", "--links", "--db", links_db, "--fresh", "--otlp-endpoint",
                 "http://localhost:4318/v1/traces"]) == 0
    assert capsys.readouterr().out == untraced
    [(root, runs)] = tree(holder["exporter"])
    assert root == "eval links" and [n for n, _ in runs] == ["run links"]
    assert [n for n, _ in runs[0][1]] == ["step judge"]  # the untraced run stored the vectors


def test_serve_names_the_endpoint_only_when_tracing(tmp_path, monkeypatch, capsys, setup_into_memory):
    import flask

    monkeypatch.setattr(flask.Flask, "run", lambda self, **kwargs: None)
    monkeypatch.setattr("jobhunt.enrich.jobs.Worker", _NoWorker)
    monkeypatch.setattr("jobhunt.prune.Pruner", _NoWorker)
    args = ["serve", "--db", f"sqlite:///{tmp_path / 'x.db'}", "--documents", str(tmp_path)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "tracing:" not in out and "span content" not in out
    assert main([*args, "--otlp-endpoint", "http://127.0.0.1:4318/v1/traces"]) == 0
    out = capsys.readouterr().out
    assert "  tracing:   http://127.0.0.1:4318/v1/traces" in out and "span content" not in out
    assert not tracing.enabled()  # shut down when serve stopped
    assert main([*args, "--otlp-endpoint", "http://127.0.0.1:4318/v1/traces", "--trace-content"]) == 0
    assert "span content: on" in capsys.readouterr().out


class _NoWorker:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


# --- Turning it on for real (1.3) ---


def test_setup_exports_to_the_endpoint_in_batches(monkeypatch):
    """setup builds its own provider with a batch processor and an OTLP/HTTP exporter for the endpoint, names the
    service only, and its shutdown sends what is left and turns tracing off."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    made = {}
    real_init = OTLPSpanExporter.__init__

    def exporter_init(self, *args, **kwargs):
        made["exporter"] = kwargs
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(OTLPSpanExporter, "__init__", exporter_init)
    exported = []
    monkeypatch.setattr(OTLPSpanExporter, "export", lambda self, spans: exported.extend(spans) or _success())
    providers = []
    real_add = TracerProvider.add_span_processor
    monkeypatch.setattr(TracerProvider, "add_span_processor",
                        lambda self, p: providers.append((self, p)) or real_add(self, p))
    shutdown = tracing.setup("http://localhost:4318/v1/traces")
    try:
        assert tracing.enabled() and not tracing.content()
        [(provider, processor)] = providers
        assert isinstance(processor, BatchSpanProcessor)
        assert made["exporter"]["endpoint"] == "http://localhost:4318/v1/traces"
        assert dict(provider.resource.attributes).keys() >= {"service.name", "service.version"}
        assert provider.resource.attributes["service.name"] == "jobhunt"
        assert not any(k.startswith(("host.", "process.", "os.")) for k in provider.resource.attributes)
        with tracing.run("posting", origin="app") as run:
            run.finish("succeeded")
    finally:
        shutdown()
    assert [s.name for s in exported] == ["run posting"] and not tracing.enabled()


def _success():
    from opentelemetry.sdk.trace.export import SpanExportResult

    return SpanExportResult.SUCCESS


def test_shutdown_is_bounded_with_nothing_listening(monkeypatch):
    import socket
    import time

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(tracing, "SHUTDOWN_SECONDS", 1)
    shutdown = tracing.setup(f"http://127.0.0.1:{port}/v1/traces")
    with tracing.run("posting", origin="app") as run:
        run.finish("succeeded")
    began = time.monotonic()
    shutdown()
    assert time.monotonic() - began < 3 and not tracing.enabled()
