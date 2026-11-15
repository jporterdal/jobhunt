"""`jobhunt mcp`: what must be named before anything is shared, the refusals (each before or without changing the
database), the start-up lines on stderr, and one stdio round trip with the SDK's client."""

import builtins
import os
import sys
from pathlib import Path

import pytest

from jobhunt import cli, migrate
from jobhunt.cli import main
from jobhunt.db import init_db, make_engine

from .conftest import add_posting

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def db_file(tmp_path):
    """A SQLite database at head with one posting; returns its URL."""
    path = tmp_path / "jobhunt.db"
    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    add_posting(engine)
    engine.dispose()
    return f"sqlite:///{path}"


def refused(argv, capsys):
    """(exit status, stderr) of a refused start; stdout must stay empty."""
    try:
        status = main(argv)
    except SystemExit as exc:  # argparse's own refusals
        status = exc.code
    out, err = capsys.readouterr()
    assert out == ""
    return status, err


def assert_warning(err):
    flat = " ".join(err.split())
    assert "may send them to a model outside this machine" in flat
    assert "postings:" in flat and "profile:" in flat
    assert f'"{cli.MCP_LOCAL_SECTION}" in {cli.MCP_DOCS}' in flat


# --- naming what is shared (5.1) ---


@pytest.mark.parametrize("argv", [[], ["--share", ""], ["--share", " , "]])
def test_nothing_named_is_refused_before_opening_the_database(tmp_path, capsys, argv):
    missing = tmp_path / "none" / "jobhunt.db"
    status, err = refused(["mcp", "--db", f"sqlite:///{missing}", *argv], capsys)
    assert status == 2
    assert_warning(err)
    assert not missing.parent.exists()


def test_unknown_scope(tmp_path, capsys):
    missing = tmp_path / "none" / "jobhunt.db"
    status, err = refused(["mcp", "--db", f"sqlite:///{missing}", "--share", "postings,everything"], capsys)
    assert status == 2
    assert "unknown scope 'everything'" in err and "postings, profile" in err
    assert_warning(err)
    assert not missing.parent.exists()


def test_environment_does_not_opt_in(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("JOBHUNT_MCP_SHARE", "postings,profile")
    status, err = refused(["mcp", "--db", f"sqlite:///{tmp_path / 'jobhunt.db'}"], capsys)
    assert status == 2
    assert_warning(err)


def test_remote_trace_endpoint(db_file, capsys):
    status, err = refused(
        ["mcp", "--db", db_file, "--share", "postings", "--otlp-endpoint", "https://traces.example.com/v1/traces"],
        capsys,
    )
    assert status == 2 and "only sent to this machine" in err


def test_help_carries_the_warning(capsys):
    with pytest.raises(SystemExit) as exited:
        main(["mcp", "--help"])
    assert exited.value.code == 0
    assert_warning(capsys.readouterr().out)


def test_the_pointer_names_a_heading_in_the_docs():
    page = (REPO / cli.MCP_DOCS).read_text(encoding="utf-8")
    headings = [line.lstrip("#").strip() for line in page.splitlines() if line.startswith("#")]
    assert cli.MCP_LOCAL_SECTION in headings


# --- refusing a database (5.2) ---


def test_missing_package(db_file, capsys, monkeypatch):
    real_import = builtins.__import__

    def no_mcp(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mcp" or name.startswith("mcp.") or (level and "mcp_server" in (fromlist or ())):
            raise ImportError("No module named 'mcp'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "jobhunt.mcp_server", raising=False)
    monkeypatch.setattr(builtins, "__import__", no_mcp)
    status, err = refused(["mcp", "--db", db_file, "--share", "postings"], capsys)
    assert status == 2 and 'pip install -e ".[mcp]"' in err


def test_missing_database_file(tmp_path, capsys):
    pytest.importorskip("mcp", reason="without the extra the command stops at the install hint first")
    missing = tmp_path / "data" / "jobhunt.db"
    status, err = refused(["mcp", "--db", f"sqlite:///{missing}", "--share", "postings"], capsys)
    assert status == 2 and "never creates a database" in err
    assert not missing.exists() and not missing.parent.exists()


def test_database_at_an_older_revision(db_file, capsys):
    pytest.importorskip("mcp", reason="without the extra the command stops at the install hint first")
    from alembic.script import ScriptDirectory

    engine = make_engine(db_file)
    revisions = ScriptDirectory.from_config(migrate.config())
    previous = revisions.get_revision(migrate.head_revision()).down_revision
    migrate.downgrade(engine, previous)
    status, err = refused(["mcp", "--db", db_file, "--share", "postings"], capsys)
    assert status == 2 and "run `jobhunt import` or `jobhunt serve` once to upgrade it" in err
    assert migrate.current_revision(engine) == previous
    engine.dispose()


def test_start_up_lines_name_the_scopes_and_database(db_file, capsys, monkeypatch):
    pytest.importorskip("mcp", reason="the mcp extra isn't installed")
    from jobhunt import mcp_server

    served = []
    monkeypatch.setattr(mcp_server, "serve", lambda engine, scopes: served.append(scopes))
    assert main(["mcp", "--db", db_file, "--share", "postings,profile"]) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert "sharing postings, profile" in err and f"database:  {db_file} (read-only)" in err
    assert served == [("postings", "profile")]


# --- a stdio round trip (5.3) ---


def test_stdio_round_trip(db_file, tmp_path, monkeypatch):
    """The SDK's client starts the command as a subprocess over pipes: no network. Its stderr goes to a file."""
    pytest.importorskip("mcp", reason="the mcp extra isn't installed")
    import anyio
    import mcp.client.client as client_module
    from mcp import Client, StdioServerParameters

    from jobhunt import mcp_tools
    from jobhunt.db import read_only_engine

    errlog = (tmp_path / "stderr.txt").open("w+", encoding="utf-8")
    original = client_module.stdio_client
    monkeypatch.setattr(client_module, "stdio_client", lambda server: original(server, errlog=errlog))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("JOBHUNT_", "OTEL_"))}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "jobhunt.cli", "mcp", "--db", db_file, "--share", "postings"], env=env,
        cwd=str(tmp_path),
    )

    async def script():
        async with Client(params) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            return tools, await client.call_tool("search_postings", {})

    tools, result = anyio.run(script)
    assert tools == {"search_postings", "get_posting"}
    assert not result.is_error
    engine = read_only_engine(db_file)
    with engine.connect() as conn:
        assert result.structured_content == mcp_tools.search_postings(conn)
    engine.dispose()
    errlog.seek(0)
    err = errlog.read()
    assert "sharing postings" in err and db_file.removeprefix("sqlite:///") in err
