"""Spans of MCP tool calls (model-tracing, "Spans for MCP tool calls"): one server span per call that starts a tool,
each its own trace, with counts and sizes and no text by default; the arguments with content on, the result never.
Needs both the mcp and otel extras."""

import builtins
import json
import socket

import pytest

pytest.importorskip("mcp", reason="the mcp extra isn't installed")

import anyio  # noqa: E402  (installed with mcp)

pytest.importorskip("opentelemetry.sdk", reason="the otel extra isn't installed")

from mcp import Client  # noqa: E402
from opentelemetry.trace import SpanKind, StatusCode  # noqa: E402

from jobhunt import mcp_server, mcp_tools, userdata  # noqa: E402
from jobhunt.cli import main  # noqa: E402
from jobhunt.enrich import tracing  # noqa: E402

from .conftest import add_posting  # noqa: E402

ALL = ("postings", "profile")
FIXED = {
    "mcp.method.name": "tools/call",
    "gen_ai.operation.name": "execute_tool",
    "network.transport": "pipe",
}


@pytest.fixture
def db(engine):
    first = add_posting(engine, "data-automation.json")
    second = add_posting(engine, "senior-ai-engineer.json")
    long_text = ("Example Robotics needs Python. " * 800).strip()  # 24,799 characters
    third = add_posting(engine, "innovation-lab.json", description_text=long_text)
    with engine.begin() as conn:
        userdata.add_profile_skill(conn, "Python", "proficient")
        userdata.add_skill_mark(conn, first, "Python", "Design", importance="required")
        userdata.add_skill_mark(conn, second, "Kubernetes", "Design", importance="preferred")
        userdata.add_tag(conn, first, "shortlist")
    return {"engine": engine, "first": first, "second": second, "long": third}


def session(engine, script, scopes=ALL):
    async def main_():
        async with Client(mcp_server.build(engine, scopes)) as client:
            return await script(client)

    return anyio.run(main_)


def call(engine, name, arguments):
    async def script(client):
        return await client.call_tool(name, arguments)

    return session(engine, script)


def spans(exporter):
    return sorted(exporter.get_finished_spans(), key=lambda s: s.start_time)


def span_strings(exporter) -> str:
    """Every name, attribute value, status description and event of the exported spans, as one text."""
    out = []
    for s in exporter.get_finished_spans():
        out.append(s.name)
        out += [str(v) for v in s.attributes.values()]
        if s.status.description:
            out.append(s.status.description)
        for event in s.events:
            out.append(event.name)
            out += [str(v) for v in event.attributes.values()]
    return "\n".join(out)


def strings_in(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in strings_in(v)]
    if isinstance(value, list):
        return [t for v in value for t in strings_in(v)]
    return []


# --- the helper (6.1) ---


def test_tool_span_and_its_attributes(traced):
    with tracing.tool("get_posting", {"job_id": 12}) as span:
        span.set(posting_id=12, items=1, chars=345, truncated=None)
    [s] = spans(traced)
    assert (s.name, s.kind, s.parent) == ("tools/call get_posting", SpanKind.SERVER, None)
    assert dict(s.attributes) == FIXED | {
        "gen_ai.tool.name": "get_posting", "jobhunt.posting.id": 12, "jobhunt.mcp.result.items": 1,
        "jobhunt.mcp.result.chars": 345,
    }


def test_tool_span_refuses_unknown_attributes(traced):
    with pytest.raises(KeyError), tracing.tool("search_postings", {}) as span:
        span.set(title="Senior AI Engineer")


def test_tool_span_is_its_own_trace_even_inside_another_span(traced):
    with tracing.root("eval skills"), tracing.tool("profile_skills", {}):
        pass
    tool_span = next(s for s in spans(traced) if s.name == "tools/call profile_skills")
    root_span = next(s for s in spans(traced) if s.name == "eval skills")
    assert tool_span.parent is None and tool_span.context.trace_id != root_span.context.trace_id


def test_arguments_only_with_content(traced):
    with tracing.tool("search_postings", {"q": "Example Robotics"}):
        pass
    assert "Example Robotics" not in span_strings(traced)


def test_arguments_with_content(traced_content):
    with tracing.tool("search_postings", {"q": "Example Robotics", "limit": 5}):
        pass
    [s] = spans(traced_content)
    assert json.loads(s.attributes["gen_ai.tool.call.arguments"]) == {"q": "Example Robotics", "limit": 5}


# --- spans through the server (6.2) ---


def test_one_span_per_call_with_its_counts(db, traced):
    engine = db["engine"]
    calls = [
        ("search_postings", {"limit": 2}),
        ("get_posting", {"job_id": db["long"]}),
        ("posting_fit", {"job_id": db["first"]}),
        ("profile_skills", {}),
        ("recommendations", {}),
    ]
    results = []
    for name, arguments in calls:
        result = call(engine, name, arguments)
        assert not result.is_error
        results.append(result.structured_content)
    exported = spans(traced)
    assert [s.name for s in exported] == [f"tools/call {name}" for name, _ in calls]
    assert len({s.context.trace_id for s in exported}) == len(calls)
    assert all(s.parent is None and s.kind == SpanKind.SERVER for s in exported)
    search, posting, fit, skills, ranked = exported
    for s, result in zip(exported, results, strict=True):
        assert {k: s.attributes[k] for k in FIXED} == FIXED
        assert s.attributes["jobhunt.mcp.result.chars"] == len(json.dumps(result, ensure_ascii=False))
    assert (search.attributes["jobhunt.mcp.result.items"], search.attributes["jobhunt.mcp.result.total"]) == (2, 3)
    assert posting.attributes["jobhunt.posting.id"] == db["long"]
    assert posting.attributes["jobhunt.mcp.result.truncated"] is True
    assert posting.attributes["jobhunt.mcp.result.items"] == 1
    assert fit.attributes["jobhunt.posting.id"] == db["first"] and fit.attributes["jobhunt.mcp.result.items"] == 1
    assert skills.attributes["jobhunt.mcp.result.items"] == 1
    assert ranked.attributes["jobhunt.mcp.result.items"] == len(results[4]["postings"])
    assert "jobhunt.mcp.result.total" not in posting.attributes


def test_unknown_posting_span(db, traced):
    result = call(db["engine"], "get_posting", {"job_id": 999})
    assert result.is_error
    [s] = spans(traced)
    assert s.status.status_code == StatusCode.ERROR and s.status.description is None
    assert s.attributes["error.type"] == "NotFound" and s.attributes["jobhunt.posting.id"] == 999


def test_refused_calls_and_listing_emit_no_span(db, traced):
    async def script(client):
        await client.list_tools()
        for name, arguments in (("search_postings", {"sort": "salary"}), ("search_postings", {"limit": 500}),
                                ("get_posting", {}), ("nope", {})):
            assert (await client.call_tool(name, arguments)).is_error

    session(db["engine"], script)
    assert spans(traced) == []


def test_a_sifted_call_counts_what_was_ignored_without_naming_it(db, traced):
    result = call(db["engine"], "search_postings", {"q": "Example", "Zqcompany": "Example Labs", "sort": "Zqsort"})
    assert not result.is_error and len(result.structured_content["warnings"]) == 2
    [s] = spans(traced)
    assert s.attributes["jobhunt.mcp.arguments.ignored"] == 2
    assert "Zq" not in span_strings(traced) and "Example Labs" not in span_strings(traced)


def test_a_call_with_nothing_ignored_has_no_ignored_count(db, traced):
    call(db["engine"], "search_postings", {"q": "Example"})
    [s] = spans(traced)
    assert "jobhunt.mcp.arguments.ignored" not in s.attributes


def test_unshared_tool_emits_no_span(db, traced):
    async def script(client):
        return await client.call_tool("profile_skills", {})

    assert session(db["engine"], script, scopes=("postings",)).is_error
    assert spans(traced) == []


# --- no text (6.3) ---


def test_no_text_by_default(db, traced):
    engine = db["engine"]
    texts = []
    for name, arguments in (
        ("search_postings", {"q": "Example Robotics", "tag": "shortlist"}),
        ("search_postings", {}),
        ("get_posting", {"job_id": db["first"]}),
        ("posting_fit", {"job_id": db["first"]}),
        ("profile_skills", {}),
        ("recommendations", {}),
    ):
        texts += strings_in(call(engine, name, arguments).structured_content)
    found = span_strings(traced)
    assert "Example Robotics" not in found and "shortlist" not in found
    for text in {t for t in texts if len(t) >= 4 and not t.startswith("20")}:
        assert text not in found, text


def test_content_on_holds_the_arguments_and_nothing_of_the_result(db, traced_content):
    result = call(db["engine"], "search_postings", {"q": "Example Robotics", "tag": "shortlist"})
    [s] = spans(traced_content)
    arguments = json.loads(s.attributes["gen_ai.tool.call.arguments"])
    assert (arguments["q"], arguments["tag"]) == ("Example Robotics", "shortlist")
    rest = span_strings(traced_content).replace(s.attributes["gen_ai.tool.call.arguments"], "")
    for text in {t for t in strings_in(result.structured_content) if len(t) >= 4 and not t.startswith("20")}:
        assert text not in rest, text


# --- tracing changes nothing (6.4) ---


def test_same_result_with_tracing_on_and_off(db):
    engine = db["engine"]
    calls = [("search_postings", {}), ("get_posting", {"job_id": db["long"]}),
             ("posting_fit", {"job_id": db["first"]}), ("profile_skills", {}), ("recommendations", {})]
    off = [call(engine, n, a).structured_content for n, a in calls]
    with pytest.MonkeyPatch.context():
        from .conftest import _tracing_into_memory

        with _tracing_into_memory(False) as exporter:
            on = [call(engine, n, a).structured_content for n, a in calls]
        assert len(exporter.get_finished_spans()) == len(calls)
    assert on == off


def test_off_exports_nothing_and_contacts_nothing(db, monkeypatch):
    tracing.reset()

    def refuse(*_args, **_kwargs):
        raise AssertionError("an address was contacted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for name in mcp_tools.TOOLS:
        arguments = {"job_id": db["first"]} if name in ("get_posting", "posting_fit") else {}
        assert not call(db["engine"], name, arguments).is_error
    assert not tracing.enabled()


def test_endpoint_without_the_otel_extra_warns_once_and_serves(db, tmp_path, monkeypatch, capsys):
    from sqlalchemy.engine import make_url

    url = make_url(str(db["engine"].url))
    if url.get_backend_name() != "sqlite":
        pytest.skip("the command's database here is a SQLite file")
    served = []
    monkeypatch.setattr(mcp_server, "serve", lambda engine, scopes: served.append(tracing.enabled()))
    real_import = builtins.__import__

    def no_sdk(name, *args, **kwargs):
        if name.startswith("opentelemetry.sdk") or name.startswith("opentelemetry.exporter"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    status = main(["mcp", "--db", f"sqlite:///{url.database}", "--share", "postings",
                   "--otlp-endpoint", "http://localhost:4318/v1/traces"])
    out, err = capsys.readouterr()
    assert status == 0 and out == "" and served == [False]
    assert err.count("warning") == 1 and 'pip install -e ".[otel]"' in err
