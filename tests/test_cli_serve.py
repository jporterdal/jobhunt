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
