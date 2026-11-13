"""Tracing off (model-tracing): every helper passes through, nothing is imported, stored output has no trace ids,
and a missing otel extra warns and carries on. Needs no OpenTelemetry package."""

import builtins
import json
import subprocess
import sys

import pytest

from jobhunt import userdata
from jobhunt.db import posting_enrichments
from jobhunt.enrich import jobs, tracing

from .conftest import add_posting
from .fakes import FakeLLM, FakeOllama, label_lines, skill
from .test_userdata import JOB, all_rows, write


@pytest.fixture(autouse=True)
def off():
    tracing.reset()
    yield
    tracing.reset()


def test_helpers_pass_through():
    llm = FakeLLM({"lines": [{"lines": [{"line": 1, "label": "other"}]}]})
    assert tracing.chat(llm, "system", "user", {"required": ["lines"]}) == {"lines": [{"line": 1, "label": "other"}]}
    assert [(r.system, r.user) for r in llm.requests] == [("system", "user")]
    client = FakeOllama()
    assert tracing.embed(client, "nomic-embed-text:latest", ["Python"]) == client.embed("nomic-embed-text:latest",
                                                                                         ["Python"])
    for manager in (tracing.root("eval skills"), tracing.run("posting", origin="app", title="anything"),
                    tracing.step("skills", "atomic@2", posting_key="python")):
        with manager as handle:
            handle.set(run_id=1, anything="goes")
            handle.fail(RuntimeError("x"))
            handle.finish("not even a status")
            assert not handle.recording
    tracing.record_usage({"prompt_eval_count": 1})
    assert tracing.ids() is None and tracing.with_ids({"a": 1}) == {"a": 1}
    assert not tracing.enabled() and not tracing.content()


def test_errors_pass_through_unchanged():
    error = ValueError("kept")
    with pytest.raises(ValueError) as raised, tracing.run("posting", origin="app"), tracing.step("skills", None):
        raise error
    assert raised.value is error


def test_setup_without_an_endpoint_creates_nothing():
    shutdown = tracing.setup(None, content=True)
    assert not tracing.enabled() and not tracing.content()
    shutdown()


def test_missing_extra_warns_once_and_leaves_tracing_off(monkeypatch, capsys):
    real_import = builtins.__import__

    def no_opentelemetry(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_opentelemetry)
    shutdown = tracing.setup("http://localhost:4318/v1/traces")
    err = capsys.readouterr().err
    assert err.count("warning") == 1 and 'pip install -e ".[otel]"' in err and "tracing is off" in err
    assert not tracing.enabled()
    shutdown()


def test_nothing_is_imported_with_tracing_off(tmp_path):
    """In a fresh interpreter, a posting job, a document-style step and link judging import no opentelemetry."""
    script = f"""
import sys
from jobhunt.db import init_db, make_engine
from jobhunt.enrich import cv, jobs, links, tracing
from jobhunt.enrich.ollama import OllamaClient
from tests.conftest import add_posting
from tests.fakes import FakeOllama
from jobhunt import userdata

engine = make_engine("sqlite:///{tmp_path / 'off.db'}")
init_db(engine)
add_posting(engine)
with engine.begin() as conn:
    userdata.set_setting(conn, "llm.model", "gemma4:12b")
    jobs.enqueue(conn, 1)
assert jobs.run_next(engine, FakeOllama()) in ("done", "failed")
cv.run_document("EXPERIENCE\\nEngineer, Example Co", FakeOllama())
tracing.setup(None)()
OllamaClient("http://127.0.0.1:9")
assert not [m for m in sys.modules if m.startswith("opentelemetry")], sorted(sys.modules)
"""
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=_repo_root())
    assert done.returncode == 0, done.stderr


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


def test_stored_output_has_no_trace_ids(engine):
    add_posting(engine)
    write(engine, userdata.set_setting, "llm.model", "gemma4:12b")
    write(engine, jobs.enqueue, JOB)
    llm = FakeLLM({
        "lines": [label_lines({"data lineage": "required"})],
        "skills": [{"skills": [skill(1, "Data lineage", "data lineage")]}],
    })
    assert jobs.run_next(engine, llm) == "done"
    [run] = all_rows(engine, posting_enrichments)
    assert "otel" not in json.loads(run.output_json) and "otel" not in run.output_json
