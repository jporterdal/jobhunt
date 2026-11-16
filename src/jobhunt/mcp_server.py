"""The MCP server (`jobhunt mcp`): the tools of `mcp_tools` for the scopes named at start-up, over stdio.

The only module that imports the `mcp` SDK (the optional `mcp` extra). Each tool's typed signature (in SIGNATURES)
is its input schema (enumerations from the read models' own tuples, ranges for numbers, no unknown argument) and
its return annotation is its output schema. The advertised schema is strict, but a call is sifted rather than
refused: an unknown argument or a value outside the schema is left out, the call runs with the rest (and defaults),
and the result says what was left out (`warnings`, first). A call left with nothing usable, or without a required
argument, is refused and doesn't run. Each call opens a connection of its own and a `tools/call` span around the
plain function, and `NotFound` becomes the SDK's tool error. Nothing here writes, calls a model or listens on a port.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Iterable
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp_types import ToolAnnotations
from pydantic import ConfigDict, Field, ValidationError
from sqlalchemy.engine import Engine

from . import mcp_tools, queries
from .enrich import tracing
from .mcp_tools import (
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    FitResult,
    Posting,
    ProfileSkillsResult,
    RecommendationsResult,
    SearchResult,
)

NAME = "jobhunt"

# Sent once when a client connects. Fixed text: no stored data. Some clients (ollmcp among them) never pass it to
# their model, so every sentence a model needs is also in the descriptions of the tools it applies to (below).
INSTRUCTIONS = (
    "jobhunt's stored job postings and the user's skill profile, read-only. Every stored posting is one the user "
    "saved. A posting is identified by its integer job_id, jobhunt's own posting id, which the tools return; it is "
    "never the number in a posting's original URL. A posting's `interest` and `fit` are the user's own 1-5 ratings; "
    "jobhunt's match figures come from posting_fit and recommendations. "
    "Scores, credits, gains and rankings are jobhunt's own figures, the same as its web pages show. Each posting's "
    "`url` is its original web address."
)

# What a model must know, in the description of every tool it applies to. Fixed text: no stored data.
_SAVED = "Every stored posting is one the user saved."
_JOB_ID = (
    "Takes a posting's `job_id`, jobhunt's own id, which search_postings and recommendations return for each "
    "posting. A job_id is never the number in a posting's URL; search_postings finds a posting by that number "
    "(as `q`), or by its title or company."
)
_RATINGS = "A posting's `interest` and `fit` are the user's own 1-5 ratings, not match scores."
_FIGURES = (
    "Scores, credits, gains and rankings are jobhunt's own figures, computed from the user's profile and skill "
    "links, the same figures its web pages show."
)
_CITE = "Each posting's `url` is its original web address."
# Leads `q`'s description and is in search_postings': models joined title and company into one `q` when how `q`
# matches came later. No example values: models copied a combined example and invented a `company` argument after a
# company example (add-mcp-server design D9, "Measured wording"). Any rewording is measured and adopted by the rule in
# docs/mcp-eval.md (scripts/mcp_eval/, the mcp-evaluation spec).
_ONE_PHRASE = (
    "`q` is matched as a substring, ignoring case: a posting matches when its title, its company or its description "
    "contains the whole of `q`, exactly as written."
)

DESCRIPTIONS = {
    "search_postings": (
        f"Search the user's stored postings with the postings list's filters and sort, a page at a time. {_SAVED} "
        f"{_ONE_PHRASE} Returns the number of matches (`total`), the filters that left postings out "
        "(`filters_used`, including the default that hides dismissed postings), how many postings match with each "
        "of those filters removed and the rest kept (`total_without`), the page's postings and, when more remain, "
        "`next_offset`. Each posting's `job_id` is the id get_posting and posting_fit take (not the number "
        f"in its URL). {_RATINGS} recommendations ranks postings by how well they match the user, and posting_fit "
        f"gives one posting's match. {_CITE}"
    ),
    "get_posting": (
        "One posting's latest version: its fields, the user's triage, its details and its description as plain "
        f"text (cut at 20,000 characters, with the full length and a flag when cut). {_JOB_ID} {_RATINGS} {_CITE}"
    ),
    "posting_fit": (
        "How well a posting matches the user's profile: its match `score` (0 to 1), the skills it asks for that the "
        "user has (with the profile skill, level, relation and credit) and those they don't have (with the reason). "
        f"{_JOB_ID} {_FIGURES} {_CITE}"
    ),
    "profile_skills": (
        "The skills in the user's profile with their levels (missing < learning < familiar < proficient < expert), "
        "whether the user or a model set the level, and their aliases; highest level first. Every skill is listed."
    ),
    "recommendations": (
        f"The user's saved postings that match them best, best first. {_SAVED} Each comes with its match `score` "
        "(0 to 1), its `value` (the score weighted by the user's interest, which sets the order) and its `gaps` (the "
        "skills it asks for that the user has least); dismissed postings and those with an application are left out. "
        "With a workplace filter, `considered_without` says how many postings would be considered without it. "
        "Also the skills that would raise those matches most (`gain`), with the postings each would raise. "
        f"{_FIGURES} {_CITE}"
    ),
}

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

Workplace = Literal[queries.WORKPLACE_TYPES]
Status = Literal[queries.STATUS_FILTERS]
Dismissed = Literal[queries.DISMISSED_MODES]
Sort = Literal[queries.SORTS]
JobId = Annotated[int, Field(description=(
    "jobhunt's own posting id: the `job_id` of a posting in search_postings or recommendations results "
    "(never the number in the posting's original URL; search_postings with that number as `q` can find its job_id)"
))]


def _call(engine: Engine, name: str, arguments: dict | None, warnings: list[str]) -> dict:
    """Run one plain tool with the arguments `_Sifted` kept, on a connection of its own, inside its span; the
    result leads with the warnings. No arguments kept means refused: a tool error, and no span (nothing ran).
    NotFound becomes the SDK's tool error."""
    if arguments is None:
        raise ToolError(f"Nothing usable in the arguments, so {name} did not run: {' '.join(warnings)}")
    try:
        with tracing.tool(name, arguments) as span, engine.connect() as conn:
            span.set(posting_id=arguments.get("job_id"), ignored=len(warnings) or None)
            result = mcp_tools.TOOLS[name](conn, **arguments)
            span.set(
                items=mcp_tools.result_items(name, result),
                total=result.get("total"),
                truncated=result.get("description_truncated"),
            )
            if warnings:
                result = {"warnings": warnings, **result}
            if span.recording:
                span.set(chars=len(json.dumps(result, ensure_ascii=False)))
            return result
    except mcp_tools.NotFound as exc:
        raise ToolError(str(exc)) from None


def _sift(arg_model: type[ArgModelBase], name: str, given: dict[str, Any]) -> tuple[dict | None, list[str]]:
    """The arguments of `given` that the schema accepts, each checked on its own, and a sentence for each left
    out (an unknown name, or a value outside the schema, with pydantic's reason, which never quotes the value).
    None instead of the arguments when the call can't run: nothing given was usable, or a required argument
    (job_id) is missing or unusable."""
    fields = arg_model.model_fields
    kept: dict[str, Any] = {}
    problems: list[tuple[str, bool]] = []  # (what is wrong, whether a default stands in)
    for key, value in given.items():
        if key not in fields:
            problems.append((f"`{key}` is not an argument of {name}", False))
            continue
        try:
            arg_model.model_validate({key: value})
        except ValidationError as exc:
            reasons = [error["msg"] for error in exc.errors() if error["loc"][:1] == (key,)]
            if reasons:
                problem = f"`{key}` is outside the schema ({'; '.join(reasons)})"
                problems.append((problem, not fields[key].is_required()))
                continue
        kept[key] = value
    try:
        arguments = arg_model.model_validate(kept).model_dump_one_level()
    except ValidationError as exc:  # only a required argument can be missing now
        arguments = None
        problems += [(f"`{error['loc'][0]}` is required", False) for error in exc.errors() if error["loc"]]
    if arguments is None or (given and not kept):
        return None, [f"{problem}." for problem, _ in problems]
    return arguments, [
        f"{problem}, so it was ignored{', and its default was used' if default else ''}."
        for problem, default in problems
    ]


class _Sifted(FuncMetadata):
    """The SDK's argument handling with `_sift` in place of all-or-nothing validation: the tool function (`_call`
    bound to an engine and a tool name) receives the kept arguments and the warnings."""

    tool_name: str

    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        given = self.pre_parse_json(arguments_to_validate)
        arguments, warnings = _sift(self.arg_model, self.tool_name, given)
        return {"arguments": arguments, "warnings": warnings}


# One typed function per tool, for its schemas only (`build` runs `_call` instead): the signature is the input
# schema, the return annotation the output schema. Each tool's description is DESCRIPTIONS[name]; the argument
# descriptions are here.
def search_postings(
    q: Annotated[str, Field(description=(
        f"{_ONE_PHRASE} It is found, ignoring case, in the title, company or description. Or a posting's exact "
        "external id, which for many sources is the number in its URL"
    ))] = "",
    tag: Annotated[str, Field(description="Only postings with this tag (one of the user's own tags)")] = "",
    min_interest: Annotated[int | None, Field(
        ge=1, le=5, description="Only postings the user rated at least this interest (1-5)"
    )] = None,
    unrated: Annotated[bool, Field(description="Only postings without an interest rating")] = False,
    workplace: Annotated[Workplace | None, Field(
        description="Only this workplace type: one value, not a list"
    )] = None,
    status: Annotated[Status | None, Field(description="Application status: any, none or one status")] = None,
    dismissed: Annotated[Dismissed, Field(description="Dismissed postings: hidden, included or only")] = "hidden",
    sort: Annotated[Sort, Field(description="Newest first by last seen, first seen, posted date, or interest")]
    = "last_seen",
    limit: Annotated[int, Field(
        ge=1, le=SEARCH_LIMIT_MAX, description=f"Postings per page, at most {SEARCH_LIMIT_MAX}"
    )] = SEARCH_LIMIT_DEFAULT,
    offset: Annotated[int, Field(ge=0, description="Postings to skip: the previous page's `next_offset`")] = 0,
) -> SearchResult: ...


def get_posting(job_id: JobId) -> Posting: ...


def posting_fit(job_id: JobId) -> FitResult: ...


def profile_skills() -> ProfileSkillsResult: ...


def recommendations(
    workplace: Annotated[list[Workplace], Field(description=(
        "Workplace types to consider, as a list; empty or all three means no filter"
    ))] = [],  # noqa: B006 (pydantic copies defaults; the list is never changed)
) -> RecommendationsResult: ...


SIGNATURES: dict[str, Callable] = {
    "search_postings": search_postings,
    "get_posting": get_posting,
    "posting_fit": posting_fit,
    "profile_skills": profile_skills,
    "recommendations": recommendations,
}


def _tool(engine: Engine, name: str) -> Tool:
    """The tool `name`: its schemas from SIGNATURES[name], its input schema strict (unknown arguments not allowed:
    the SDK's model ignores them), and a call sifted by `_Sifted` and run by `_call`."""
    tool = Tool.from_function(
        SIGNATURES[name], name=name, description=DESCRIPTIONS[name], annotations=READ_ONLY, structured_output=True,
    )
    meta = tool.fn_metadata
    base = meta.arg_model
    strict = type(base.__name__, (base,), {"model_config": ConfigDict(arbitrary_types_allowed=True, extra="forbid")})
    tool.parameters = strict.model_json_schema(by_alias=True)
    tool.fn_metadata = _Sifted(
        arg_model=strict, output_schema=meta.output_schema, output_model=meta.output_model,
        wrap_output=meta.wrap_output, tool_name=name,
    )
    tool.fn = functools.partial(_call, engine, name)
    return tool


def build(engine: Engine, scopes: Iterable[str]) -> MCPServer:
    """A server offering the tools of `scopes` (names from mcp_tools.SCOPES), reading through `engine`."""
    scopes = set(scopes)
    unknown = scopes - set(mcp_tools.SCOPES)
    if unknown:
        raise ValueError(f"unknown scope: {', '.join(sorted(unknown))}")
    names = [name for scope, tools in mcp_tools.SCOPES.items() if scope in scopes for name in tools]
    tools = [_tool(engine, name) for name in names]
    return MCPServer(NAME, instructions=INSTRUCTIONS, tools=tools, log_level="WARNING")


def serve(engine: Engine, scopes: Iterable[str]) -> None:
    """Serve over stdin and stdout until the client closes the connection."""
    build(engine, scopes).run("stdio")
