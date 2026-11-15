"""The MCP server through the SDK's in-memory client: the tools listed per scope with their schemas, results equal
to the plain functions', and errors (unknown posting, arguments outside the schema, unshared tools, crashes).
Skipped without the `mcp` extra."""

import pytest

pytest.importorskip("mcp", reason="the mcp extra isn't installed")

import anyio  # noqa: E402  (installed with mcp)
from mcp import Client  # noqa: E402

from jobhunt import mcp_server, mcp_tools, queries, userdata  # noqa: E402

from .conftest import add_posting  # noqa: E402

ALL = ("postings", "profile")


@pytest.fixture
def db(engine):
    first = add_posting(engine, "data-automation.json")
    second = add_posting(engine, "senior-ai-engineer.json")
    with engine.begin() as conn:
        python = userdata.add_profile_skill(conn, "Python", "proficient")
        userdata.add_skill_mark(conn, first, "Python", "Design", importance="required")
        userdata.add_skill_mark(conn, second, "Kubernetes", "Design", importance="preferred")
        userdata.add_tag(conn, first, "shortlist")
    return {"engine": engine, "first": first, "second": second, "python": python}


def run(server, script):
    """Connect to `server` in memory and run `script(client)`; returns its result."""

    async def main():
        async with Client(server) as client:
            return await script(client)

    return anyio.run(main)


def listed(engine, scopes):
    async def script(client):
        return (await client.list_tools()).tools

    return {tool.name: tool for tool in run(mcp_server.build(engine, scopes), script)}


def called(engine, scopes, name, arguments):
    async def script(client):
        return await client.call_tool(name, arguments)

    return run(mcp_server.build(engine, scopes), script)


def text(result) -> str:
    return "\n".join(part.text for part in result.content)


# --- listing (4.1) ---


@pytest.mark.parametrize("scopes, names", [
    (("postings",), {"search_postings", "get_posting"}),
    (("profile",), {"posting_fit", "profile_skills", "recommendations"}),
    (ALL, {"search_postings", "get_posting", "posting_fit", "profile_skills", "recommendations"}),
])
def test_tools_listed_per_scope(db, scopes, names):
    tools = listed(db["engine"], scopes)
    assert set(tools) == names
    for tool in tools.values():
        assert tool.description and tool.input_schema["type"] == "object" and tool.output_schema
        assert tool.input_schema.get("additionalProperties") is False
        assert tool.annotations.read_only_hint is True


def test_input_schema_names_the_allowed_values(db):
    schema = listed(db["engine"], ("postings",))["search_postings"].input_schema
    text_of = repr(schema)
    for values in (queries.SORTS, queries.DISMISSED_MODES, queries.WORKPLACE_TYPES, queries.STATUS_FILTERS):
        for value in values:
            assert repr(value) in text_of
    limit = schema["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 50, 20)
    assert "job_id" in listed(db["engine"], ALL)["get_posting"].input_schema["required"]


def test_tools_only_no_resources_or_prompts(db):
    async def script(client):
        return (await client.list_resources()).resources, (await client.list_prompts()).prompts

    assert run(mcp_server.build(db["engine"], ALL), script) == ([], [])


def test_instructions_hold_no_stored_text(db):
    server = mcp_server.build(db["engine"], ALL)
    assert server.instructions == mcp_server.INSTRUCTIONS
    for stored in ("Example Bank", "Example Labs", "Python", "shortlist", "Analytics"):
        assert stored not in mcp_server.INSTRUCTIONS


def test_descriptions_hold_no_stored_text(db):
    tools = listed(db["engine"], ALL)
    for tool in tools.values():
        text_of = tool.description + repr(tool.input_schema)
        for stored in ("Example Bank", "Example Labs", "Python", "shortlist", "Analytics", "9000000"):
            assert stored not in text_of, tool.name


# What the instructions say, by the tools it applies to: some clients pass only tool descriptions to their model.
CARRIED = {
    "saved": ("Every stored posting is one the user saved.", {"search_postings", "recommendations"}),
    "job_id": ("never the number in a posting's URL", {"get_posting", "posting_fit"}),
    "ratings": ("the user's own 1-5 ratings, not match scores", {"search_postings", "get_posting"}),
    "figures": ("the same figures its web pages show", {"posting_fit", "recommendations"}),
    "url": ("Each posting's `url` is its original web address.",
            {"search_postings", "get_posting", "posting_fit", "recommendations"}),
}

# The server describes; it doesn't instruct or advise (the user's principle): none of these in any description.
INSTRUCTING = ("Cite ", "cite it", "call search_postings first", "report them", "never recompute", "Set only",
               "leave it out", "Leave it", "Use this", "put either", "don't recompute", "use the job_id")


def test_descriptions_state_facts_not_instructions(db):
    tools = listed(db["engine"], ALL)
    texts = [mcp_server.INSTRUCTIONS] + [t.description + repr(t.input_schema) for t in tools.values()]
    for text_of in texts:
        for phrase in INSTRUCTING:
            assert phrase not in text_of, phrase


@pytest.mark.parametrize("what", CARRIED)
def test_descriptions_carry_what_the_instructions_say(db, what):
    sentence, names = CARRIED[what]
    tools = listed(db["engine"], ALL)
    assert {name for name, tool in tools.items() if sentence in tool.description} == names


def test_job_id_arguments_say_where_a_job_id_comes_from(db):
    tools = listed(db["engine"], ALL)
    for name in ("get_posting", "posting_fit"):
        described = tools[name].input_schema["properties"]["job_id"]["description"]
        assert "search_postings" in described and "never the number" in described
    search = tools["search_postings"].input_schema["properties"]
    q = search["q"]["description"]
    assert q.startswith(mcp_server._ONE_PHRASE) and "external id" in q
    assert mcp_server._ONE_PHRASE in tools["search_postings"].description
    assert "not a list" in search["workplace"]["description"]
    assert "at most 50" in search["limit"]["description"]


def test_unknown_scope_is_refused(db):
    with pytest.raises(ValueError, match="everything"):
        mcp_server.build(db["engine"], ("postings", "everything"))


# --- calling (4.2) ---


def every_call(db):
    yield "search_postings", {}
    yield "search_postings", {"tag": "shortlist", "sort": "interest", "limit": 1}
    yield "get_posting", {"job_id": db["first"]}
    yield "posting_fit", {"job_id": db["first"]}
    yield "profile_skills", {}
    yield "recommendations", {}
    yield "recommendations", {"workplace": ["Hybrid"]}


def test_structured_content_equals_the_plain_function(db):
    engine = db["engine"]
    for name, arguments in every_call(db):
        result = called(engine, ALL, name, arguments)
        assert not result.is_error, text(result)
        with engine.connect() as conn:
            assert result.structured_content == mcp_tools.TOOLS[name](conn, **arguments), name


def test_results_match_their_output_schemas(db):
    from .mcp_schemas import check, output_schemas

    engine = db["engine"]
    validators = output_schemas(engine)
    assert set(validators) == set(mcp_tools.TOOLS)
    calls = [*every_call(db), ("get_posting", {"job_id": db["second"]}), ("posting_fit", {"job_id": db["second"]}),
             ("search_postings", {"dismissed": "included", "unrated": True})]
    with engine.connect() as conn:
        for name, arguments in calls:
            check(validators, name, mcp_tools.TOOLS[name](conn, **arguments))


def test_results_match_their_output_schemas_on_an_empty_database(engine):
    """The sparse end: no postings, no profile, so every optional field is left out."""
    from .mcp_schemas import check, output_schemas

    validators = output_schemas(engine)
    with engine.connect() as conn:
        for name in ("search_postings", "profile_skills", "recommendations"):
            check(validators, name, mcp_tools.TOOLS[name](conn))


def test_a_field_the_schema_does_not_name_fails_the_check(db):
    from .mcp_schemas import check, output_schemas

    validators = output_schemas(db["engine"])
    with db["engine"].connect() as conn:
        result = mcp_tools.get_posting(conn, db["first"])
    with pytest.raises(AssertionError, match="notes"):
        check(validators, "get_posting", result | {"notes": "Zqmarker"})
    with pytest.raises(AssertionError, match="title"):
        check(validators, "get_posting", {k: v for k, v in result.items() if k != "title"})


def test_unknown_posting(db):
    result = called(db["engine"], ALL, "get_posting", {"job_id": 999})
    assert result.is_error and result.structured_content is None
    assert "No posting with id 999." in text(result)


# --- sifted arguments: unknown or out-of-schema ones are left out with a warning; nothing usable is refused ---


@pytest.mark.parametrize("name, arguments, named", [
    ("search_postings", {"sort": "salary"}, "sort"),
    ("search_postings", {"limit": 500}, "limit"),
    ("search_postings", {"min_interest": 0}, "min_interest"),
    ("search_postings", {"workplace": "Mars"}, "workplace"),
    ("search_postings", {"bogus": 1}, "bogus"),
    ("search_postings", {"company": "Example Labs", "bogus": 1}, "company"),
    ("profile_skills", {"level": "expert"}, "level"),
    ("recommendations", {"workplace": "Remote"}, "workplace"),
])
def test_a_call_with_nothing_usable_is_refused_and_never_starts_the_tool(db, monkeypatch, name, arguments, named):
    ran = []
    monkeypatch.setitem(mcp_tools.TOOLS, name, lambda *a, **k: ran.append(1))
    result = called(db["engine"], ALL, name, arguments)
    assert result.is_error and result.structured_content is None
    assert named in text(result) and f"{name} did not run" in text(result)
    assert ran == []


@pytest.mark.parametrize("arguments", [{}, {"id": 3}, {"job_id": "abc"}, {"job_id": 0.5, "verbose": True}])
def test_a_call_without_a_usable_job_id_is_refused(db, arguments):
    result = called(db["engine"], ALL, "get_posting", arguments)
    assert result.is_error and result.structured_content is None
    assert "job_id" in text(result)
    for name in arguments:
        assert f"`{name}`" in text(result)


def test_an_unknown_argument_is_ignored_and_the_rest_used(db):
    engine = db["engine"]
    result = called(engine, ALL, "search_postings", {"q": "Example", "company": "Example Bank", "limit": 1})
    assert not result.is_error
    content = result.structured_content
    assert content["warnings"] == ["`company` is not an argument of search_postings, so it was ignored."]
    with engine.connect() as conn:
        assert content == {"warnings": content["warnings"], **mcp_tools.search_postings(conn, q="Example", limit=1)}
    assert text(result).lstrip("{ \n").startswith('"warnings"')  # first in the text a model reads


def test_a_value_outside_the_schema_is_ignored_and_its_default_used(db):
    engine = db["engine"]
    result = called(engine, ALL, "search_postings", {"tag": "shortlist", "limit": 500, "sort": "salary"})
    assert not result.is_error
    limit, sort = result.structured_content["warnings"]
    assert limit.startswith("`limit` is outside the schema (") and "50" in limit
    assert limit.endswith("so it was ignored, and its default was used.")
    assert sort.startswith("`sort` is outside the schema (") and "'last_seen'" in sort
    with engine.connect() as conn:
        expected = mcp_tools.search_postings(conn, tag="shortlist")
    assert {k: v for k, v in result.structured_content.items() if k != "warnings"} == expected


def test_an_unknown_argument_beside_a_job_id(db):
    result = called(db["engine"], ALL, "posting_fit", {"job_id": db["first"], "verbose": True})
    assert not result.is_error and result.structured_content["job_id"] == db["first"]
    assert result.structured_content["warnings"] == ["`verbose` is not an argument of posting_fit, so it was ignored."]


def test_warnings_never_quote_the_value_sent(db):
    result = called(db["engine"], ALL, "search_postings", {"q": "Example", "sort": "Zqmarker", "Zqname": 1})
    assert not result.is_error
    warnings = " ".join(result.structured_content["warnings"])
    assert "Zqmarker" not in warnings and "`Zqname`" in warnings  # the name is the model's own, echoed back


@pytest.mark.parametrize("name", ["search_postings", "profile_skills", "recommendations"])
def test_a_call_without_arguments_runs_without_warnings(db, name):
    result = called(db["engine"], ALL, name, {})
    assert not result.is_error and "warnings" not in result.structured_content


def test_a_list_given_as_json_text_is_read_as_the_list(db):
    result = called(db["engine"], ALL, "recommendations", {"workplace": '["Hybrid"]'})
    assert not result.is_error and "warnings" not in result.structured_content
    assert result.structured_content["workplaces"] == ["Hybrid"]


def test_sifted_results_match_their_output_schemas(db):
    from .mcp_schemas import check, output_schemas

    validators = output_schemas(db["engine"])
    for name, arguments in [
        ("search_postings", {"bogus": 1, "q": "Example"}),
        ("get_posting", {"job_id": db["first"], "bogus": 1}),
        ("posting_fit", {"job_id": db["first"], "bogus": 1}),
        ("recommendations", {"workplace": ["Hybrid"], "bogus": 1}),
    ]:
        result = called(db["engine"], ALL, name, arguments)
        assert result.structured_content["warnings"]
        check(validators, name, result.structured_content)


def test_unshared_tool_is_unknown(db):
    result = called(db["engine"], ("postings",), "profile_skills", {})
    assert result.is_error and result.structured_content is None
    assert "Unknown tool" in text(result) and "Python" not in text(result)


def test_unexpected_exception_message_is_not_sent(db, monkeypatch):
    def crash(conn, **_):
        raise RuntimeError("Zqsecret from Example Bank")

    monkeypatch.setitem(mcp_tools.TOOLS, "profile_skills", crash)
    result = called(db["engine"], ALL, "profile_skills", {})
    assert result.is_error
    assert "Zqsecret" not in text(result) and "Example Bank" not in text(result)
