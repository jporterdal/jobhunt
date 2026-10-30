"""`jobhunt eval` against a fake client and against the stub Ollama server."""

import json

import pytest
from sqlalchemy import func, select

from jobhunt import userdata
from jobhunt.cli import build_parser, main
from jobhunt.db import init_db, make_engine, posting_enrichments

from .conftest import CANDIDATE_PIPELINE, PIPELINE, add_posting, add_run
from .test_evaluate import TEXT, eval_llm, label
from .test_ollama import Stub, closed_port_url
from .test_userdata import JOB


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'eval.db'}"
    engine = make_engine(url)
    init_db(engine)
    add_posting(engine, description_text=TEXT, description_html="<p>" + TEXT.replace("\n", "<br>") + "</p>")
    with engine.begin() as conn:
        userdata.set_setting(conn, "llm.model", "gemma4:12b")
    engine.dispose()
    return url


def with_engine(url, fn):
    engine = make_engine(url)
    try:
        return fn(engine)
    finally:
        engine.dispose()


def labelled(url):
    with_engine(url, label)


def runs(url):
    def count(engine):
        with engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(posting_enrichments)).scalar_one()

    return with_engine(url, count)


@pytest.fixture
def fake_client(monkeypatch):
    llm = eval_llm()
    monkeypatch.setattr("jobhunt.enrich.ollama.OllamaClient", lambda url: llm)
    return llm


def test_eval_options(monkeypatch):
    monkeypatch.delenv("JOBHUNT_OLLAMA_URL", raising=False)
    args = build_parser().parse_args(["eval", "--model", "phi4:latest", "--segmenter", "rules", "--fresh", "--json"])
    assert (args.model, args.segmenter, args.fresh, args.json) == ("phi4:latest", "rules", True, True)
    assert args.ollama_url == "http://localhost:11434"
    monkeypatch.setenv("JOBHUNT_OLLAMA_URL", "http://127.0.0.1:11500")
    assert build_parser().parse_args(["eval"]).ollama_url == "http://127.0.0.1:11500"


def test_no_labelled_postings(db_url, fake_client, capsys):
    assert main(["eval", "--db", db_url]) == 1
    err = capsys.readouterr().err
    assert "No labelled postings" in err and "Labelling complete" in err
    assert fake_client.requests == []


def test_text_report(db_url, fake_client, capsys):
    labelled(db_url)
    assert main(["eval", "--db", db_url]) == 0
    out = capsys.readouterr().out
    assert "model:    gemma4:12b" in out and "dev: 1 labelled postings, 1 scored" in out
    assert "holdout: 0 labelled" in out
    assert "(4/5)" in out and "unjudged" in out
    assert runs(db_url) == 1


def test_json_report(db_url, fake_client, capsys):
    labelled(db_url)
    assert main(["eval", "--db", db_url, "--json", "--segmenter", "rules"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["pipeline"].startswith("seg=rules@2")
    assert "groups" not in report and {"postings", "failures", "precision", "unjudged", "recall"} <= set(report)


def test_unreachable_exits_and_writes_nothing(db_url, capsys):
    labelled(db_url)
    assert main(["eval", "--db", db_url, "--ollama-url", closed_port_url()]) == 1
    assert "Ollama is unreachable" in capsys.readouterr().err
    assert runs(db_url) == 0


def test_against_stub_server(db_url, capsys):
    labelled(db_url)
    stub = Stub()

    def chat(body):
        key = body["format"]["required"][0]
        answers = {
            "lines": {"lines": [{"line": n, "label": "required"} for n in (2, 3, 4, 5)]},
            "skills": {"skills": [{"line": 1, "name": "PyTorch", "kind": "technical", "quote": "PyTorch"}]},
            "ranges": {"ranges": []},
        }
        return 200, {"message": {"content": json.dumps(answers[key])}}

    stub.routes["/api/chat"] = chat
    try:
        assert main(["eval", "--db", db_url, "--ollama-url", stub.url, "--json"]) == 0
    finally:
        stub.close()
    report = json.loads(capsys.readouterr().out)
    assert report["recall"]["all"]["count"] == 1 and report["misses"]["extraction"] == 3
    chats = [body for path, body in stub.requests if path == "/api/chat"]
    assert chats and all(b["model"] == "gemma4:12b" and b["options"]["temperature"] == 0 for b in chats)
    assert all(b["think"] is False for b in chats)  # gemma4:12b supports thinking in the stub


# --- Several skill extraction methods ---

def stored_runs(url):
    """Stored runs for both methods: atomic@2 finds MLflow and Python, atomic@5 finds Python only."""
    def store(engine):
        add_run(engine, JOB, skills=[("MLflow", "required", "MLflow"), ("Python", "required", "Python")])
        add_run(engine, JOB, skills=[("Python", "required", "Python")], pipeline=CANDIDATE_PIPELINE, origin="eval")

    with_engine(url, store)


def test_unknown_skill_method(db_url, fake_client, capsys, candidate):
    labelled(db_url)
    assert main(["eval", "--db", db_url, "--skills", "atomic@2,atomic@3"]) == 1
    err = capsys.readouterr().err
    assert "atomic@3" in err and "available: atomic@2, atomic@5" in err
    assert fake_client.requests == [] and runs(db_url) == 0


def test_removed_skill_method(db_url, fake_client, capsys):
    labelled(db_url)
    with_engine(db_url, lambda engine: add_run(
        engine, JOB, skills=[("Python", "required", "Python")],
        pipeline=PIPELINE.replace("skills=atomic@2", "skills=atomic@4"), origin="eval",
    ))
    assert main(["eval", "--db", db_url, "--skills", "atomic@4"]) == 1
    err = capsys.readouterr().err
    assert "atomic@4" in err and "available: atomic@2" in err
    assert fake_client.requests == [] and runs(db_url) == 1


def test_comparing_stored_runs(db_url, fake_client, capsys, candidate):
    labelled(db_url)
    stored_runs(db_url)
    assert main(["eval", "--db", db_url, "--skills", "atomic@2,atomic@5"]) == 0
    assert fake_client.requests == [] and runs(db_url) == 2
    out, err = capsys.readouterr()
    assert "atomic@2: 0 new runs, 1 reused" in err and "atomic@5: 0 new runs, 1 reused" in err
    header = next(line for line in out.splitlines() if line.strip().endswith("atomic@5"))
    assert "atomic@2" in header
    assert "dev: 1 labelled postings" in out and "holdout: 0 labelled postings" in out
    recall = next(line for line in out.splitlines() if line.startswith("recall all"))  # the dev set's
    assert "40% (2/5)" in recall and "20% (1/5)" in recall
    assert any(line.startswith("precision all") for line in out.splitlines())
    assert any(line.startswith("unjudged all") for line in out.splitlines())
    assert any(line.startswith("failed runs") for line in out.splitlines())


def test_marks_found_by_one_method_only(db_url, fake_client, capsys, candidate):
    labelled(db_url)
    stored_runs(db_url)
    assert main(["eval", "--db", db_url, "--skills", "atomic@2,atomic@5"]) == 0
    out = capsys.readouterr().out
    assert "selected marks matched by some methods only: 1" in out
    assert "    MLflow (required) “MLflow”: atomic@2" in out
    assert any(line.startswith(f"  {JOB}  ") and line.endswith("(dev)") for line in out.splitlines())

    assert main(["eval", "--db", db_url, "--skills", "atomic@2,atomic@5", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [m["skills"] for m in report["methods"]] == ["atomic@2", "atomic@5"]
    assert [m["recall"]["all"]["count"] for m in report["methods"]] == [2, 1]
    assert report["differences"] == [
        {
            "job_id": JOB,
            "title": report["differences"][0]["title"],
            "set": "dev",
            "name": "MLflow",
            "importance": "required",
            "quote": "MLflow",
            "matched_by": ["atomic@2"],
        }
    ]


def test_methods_needing_runs_refused_when_unreachable(db_url, capsys, candidate):
    labelled(db_url)
    with_engine(db_url, lambda engine: add_run(engine, JOB, skills=[("Python", "required", "Python")]))
    args = ["eval", "--db", db_url, "--skills", "atomic@2,atomic@5", "--ollama-url", closed_port_url()]
    assert main(args) == 1
    err = capsys.readouterr().err
    assert "atomic@5: 1 new runs, 0 reused" in err and "Ollama is unreachable" in err and "nothing was written" in err
    assert runs(db_url) == 1


def test_one_method_from_the_option(db_url, fake_client, capsys, candidate):
    labelled(db_url)
    assert main(["eval", "--db", db_url, "--skills", "atomic@5", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "skills=atomic@5" in report["pipeline"] and "methods" not in report
