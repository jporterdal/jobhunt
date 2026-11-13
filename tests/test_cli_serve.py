from pathlib import Path

import flask
import pytest
from sqlalchemy import inspect

from jobhunt import db, migrate
from jobhunt.cli import build_parser, main


@pytest.fixture(autouse=True)
def workers(monkeypatch):
    """Record worker starts instead of running the model queue."""
    started = []

    class FakeWorker:
        def __init__(self, engine, client):
            self.client = client

        def start(self):
            started.append(self)

        def stop(self):
            pass

        def join(self, timeout=None):
            pass

    monkeypatch.setattr("jobhunt.enrich.jobs.Worker", FakeWorker)
    return started


@pytest.fixture(autouse=True)
def pruners(monkeypatch):
    """Record pruner starts and stops instead of pruning."""
    events = []

    class FakePruner:
        def __init__(self, engine, inbox, parsers):
            self.inbox, self.parsers = inbox, parsers

        def start(self):
            events.append(("start", self))

        def stop(self):
            events.append(("stop", self))

        def join(self, timeout=None):
            events.append(("join", self))

    monkeypatch.setattr("jobhunt.prune.Pruner", FakePruner)
    return events


@pytest.fixture
def runs(monkeypatch):
    """Record app.run() calls instead of starting a server."""
    calls = []
    monkeypatch.setattr(flask.Flask, "run", lambda self, **kwargs: calls.append((self, kwargs)))
    return calls


def test_serve_defaults(monkeypatch):
    for name in ("JOBHUNT_DB_URL", "JOBHUNT_INBOX", "JOBHUNT_DOCUMENTS", "JOBHUNT_OLLAMA_URL"):
        monkeypatch.delenv(name, raising=False)
    args = build_parser().parse_args(["serve"])
    assert (args.host, args.port, args.debug) == ("127.0.0.1", 8000, False)
    assert args.db == "sqlite:///data/jobhunt.db"
    assert args.inbox == Path("inbox") and args.documents == Path("data/documents")
    assert args.ollama_url == "http://localhost:11434"


def test_serve_env_defaults_shared_with_import(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNT_DB_URL", "sqlite:///x.db")
    monkeypatch.setenv("JOBHUNT_INBOX", str(tmp_path / "in"))
    monkeypatch.setenv("JOBHUNT_DOCUMENTS", str(tmp_path / "docs"))
    serve = build_parser().parse_args(["serve"])
    imp = build_parser().parse_args(["import"])
    assert serve.db == imp.db == "sqlite:///x.db"
    assert serve.inbox == imp.inbox == tmp_path / "in"
    assert serve.documents == tmp_path / "docs"


def test_serve_options():
    args = build_parser().parse_args(
        ["serve", "--host", "0.0.0.0", "--port", "8123", "--db", "sqlite:///y.db", "--documents", "d", "--debug"]
    )
    assert (args.host, args.port, args.db, args.documents, args.debug) == (
        "0.0.0.0",
        8123,
        "sqlite:///y.db",
        Path("d"),
        True,
    )


def test_fresh_database_created_with_full_schema(tmp_path, capsys, runs):
    db_file = tmp_path / "data" / "fresh.db"
    assert (
        main(["serve", "--db", f"sqlite:///{db_file}", "--inbox", str(tmp_path), "--documents", str(tmp_path / "docs")])
        == 0
    )

    assert db_file.exists()
    engine = db.make_engine(f"sqlite:///{db_file}")
    try:
        assert set(db.metadata.tables) <= set(inspect(engine).get_table_names())
        assert migrate.current_revision(engine) == migrate.head_revision()
    finally:
        engine.dispose()
    app, kwargs = runs[0]
    assert kwargs == {"host": "127.0.0.1", "port": 8000, "debug": False, "use_reloader": False, "threaded": True}
    out = capsys.readouterr()
    assert "serving http://127.0.0.1:8000/" in out.out
    assert f"documents: {tmp_path / 'docs'}" in out.out
    assert "warning" not in out.err


def test_non_loopback_host_warns(tmp_path, capsys, runs):
    main(["serve", "--host", "0.0.0.0", "--db", f"sqlite:///{tmp_path / 'x.db'}", "--documents", str(tmp_path)])
    err = capsys.readouterr().err
    assert "warning" in err and "no authentication" in err
    assert "anyone who can reach this address can read and change your data" in err
    assert runs[0][1]["host"] == "0.0.0.0"


def serve(tmp_path, *extra):
    return main(["serve", "--db", f"sqlite:///{tmp_path / 'x.db'}", "--documents", str(tmp_path), *extra])


def test_ollama_url_from_environment(monkeypatch, tmp_path, capsys, runs, workers):
    monkeypatch.setenv("JOBHUNT_OLLAMA_URL", "http://127.0.0.1:11500")
    assert build_parser().parse_args(["serve"]).ollama_url == "http://127.0.0.1:11500"
    serve(tmp_path)
    assert "ollama:    http://127.0.0.1:11500" in capsys.readouterr().out
    app = runs[0][0]
    assert app.config["OLLAMA"].url == "http://127.0.0.1:11500" == workers[0].client.url


def test_ollama_url_option(tmp_path, capsys, runs):
    serve(tmp_path, "--ollama-url", "http://gpu-box:11434/")
    assert "ollama:    http://gpu-box:11434/" in capsys.readouterr().out
    assert runs[0][0].config["OLLAMA"].url == "http://gpu-box:11434"


def test_worker_starts_once(tmp_path, runs, workers):
    serve(tmp_path)
    assert len(workers) == 1


def test_worker_not_started_in_debug_reloader_parent(monkeypatch, tmp_path, runs, workers):
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    serve(tmp_path, "--debug")  # the parent: it only watches files
    assert workers == []
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    serve(tmp_path, "--debug")  # the child the reloader starts: it serves, so it runs the worker
    assert len(workers) == 1


def test_pruner_starts_with_the_inbox_and_stops_after_serving(tmp_path, runs, pruners):
    serve(tmp_path, "--inbox", str(tmp_path / "in"))
    assert [e for e, _ in pruners] == ["start", "stop", "join"]
    pruner = pruners[0][1]
    assert pruner.inbox == tmp_path / "in"
    assert "posting-file" in [p.name for p in pruner.parsers]


def test_pruner_not_started_in_debug_reloader_parent(monkeypatch, tmp_path, runs, pruners):
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    serve(tmp_path, "--debug")
    assert pruners == []
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    serve(tmp_path, "--debug")
    assert [e for e, _ in pruners] == ["start", "stop", "join"]


# --- Trace endpoint and content (model-tracing) ---

ACCEPTED_ENDPOINTS = [
    "http://localhost:4318/v1/traces", "http://127.0.0.1:4318/v1/traces", "http://[::1]:4318/v1/traces",
    "https://localhost/v1/traces", "http://127.8.9.10:4318/v1/traces",
]
REFUSED_ENDPOINTS = [
    "https://traces.example.com/v1/traces", "http://192.0.2.10:4318/v1/traces", "ftp://localhost/x",
    "localhost:4318", "http://localhost:notaport/v1/traces", "http://[::ffff:192.0.2.10]:4318/v1/traces",
]


@pytest.mark.parametrize("command", ["serve", "eval"])
@pytest.mark.parametrize("endpoint", ACCEPTED_ENDPOINTS)
def test_loopback_endpoints_accepted(monkeypatch, command, endpoint):
    monkeypatch.delenv("JOBHUNT_OTLP_ENDPOINT", raising=False)
    assert build_parser().parse_args([command, "--otlp-endpoint", endpoint]).otlp_endpoint == endpoint


@pytest.mark.parametrize("command", ["serve", "eval"])
@pytest.mark.parametrize("endpoint", REFUSED_ENDPOINTS)
def test_other_endpoints_refused_before_the_database_opens(tmp_path, capsys, command, endpoint):
    db_file = tmp_path / "never.db"
    with pytest.raises(SystemExit) as exited:
        main([command, "--db", f"sqlite:///{db_file}", "--otlp-endpoint", endpoint])
    assert exited.value.code == 2 and not db_file.exists()
    assert "traces are only sent to this machine" in capsys.readouterr().err


def test_tracing_off_by_default(monkeypatch):
    for name in ("JOBHUNT_OTLP_ENDPOINT", "JOBHUNT_TRACE_CONTENT", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")  # set for another tool: ignored
    for command in ("serve", "eval"):
        args = build_parser().parse_args([command])
        assert (args.otlp_endpoint, args.trace_content) == (None, False)


def test_endpoint_and_content_from_the_environment(monkeypatch):
    monkeypatch.setenv("JOBHUNT_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    monkeypatch.setenv("JOBHUNT_TRACE_CONTENT", "1")
    args = build_parser().parse_args(["eval"])
    assert (args.otlp_endpoint, args.trace_content) == ("http://127.0.0.1:4318/v1/traces", True)
    monkeypatch.setenv("JOBHUNT_TRACE_CONTENT", "yes")  # only 1 turns it on
    assert build_parser().parse_args(["serve"]).trace_content is False
    monkeypatch.setenv("JOBHUNT_OTLP_ENDPOINT", "")
    assert build_parser().parse_args(["serve"]).otlp_endpoint is None


def test_option_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("JOBHUNT_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    args = build_parser().parse_args(["serve", "--otlp-endpoint", "http://localhost:4319/v1/traces"])
    assert args.otlp_endpoint == "http://localhost:4319/v1/traces"
    monkeypatch.setenv("JOBHUNT_OTLP_ENDPOINT", "https://traces.example.com/v1/traces")  # never used
    args = build_parser().parse_args(["serve", "--otlp-endpoint", "http://localhost:4319/v1/traces"])
    assert args.otlp_endpoint == "http://localhost:4319/v1/traces"


def test_remote_endpoint_in_the_environment_refused(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("JOBHUNT_OTLP_ENDPOINT", "https://traces.example.com/v1/traces")
    with pytest.raises(SystemExit) as exited:
        serve(tmp_path)
    assert exited.value.code == 2 and "only sent to this machine" in capsys.readouterr().err


def test_serve_without_the_extra_warns_and_serves(monkeypatch, tmp_path, capsys, runs, workers):
    import builtins

    real_import = builtins.__import__

    def no_opentelemetry(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_opentelemetry)
    assert serve(tmp_path, "--otlp-endpoint", "http://localhost:4318/v1/traces") == 0
    out = capsys.readouterr()
    assert 'pip install -e ".[otel]"' in out.err and "tracing:" not in out.out
    assert len(runs) == 1 and len(workers) == 1


def test_no_tracing_line_without_an_endpoint(monkeypatch, tmp_path, capsys, runs):
    monkeypatch.delenv("JOBHUNT_OTLP_ENDPOINT", raising=False)
    serve(tmp_path)
    assert "tracing:" not in capsys.readouterr().out
