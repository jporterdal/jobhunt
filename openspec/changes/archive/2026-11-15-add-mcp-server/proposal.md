## Why

An assistant that speaks the Model Context Protocol (MCP) can only answer "which of my saved postings fit me best, and what do they still ask for?" today if the user retypes what the web pages show. An MCP server gives such a client the same read models the pages use, so the answers come from the stored postings, the skill profile and the match figures.

It is also the first feature whose purpose is to hand jobhunt's data to another program, and that program may send it to a cloud model. The project's rule is that no data leaves the machine, so what the server may hand over, and who decides, is settled here as the main design decision (design.md, D1).

## What Changes

- A new command, `jobhunt mcp`, runs an MCP server over standard input and output for the program that starts it. It uses the official `mcp` Python SDK, a new optional extra (`pip install -e ".[mcp]"`), as `otel` is. Without the extra the command says how to install it and exits; nothing else needs it.
- Five read-only tools, each a thin wrapper over a read model the web interface already uses:
  - `search_postings`: the postings list, with its filters, a page at a time;
  - `get_posting`: one posting with its description text and its original URL;
  - `posting_fit`: a posting's match score, its Have / Don't have summary and each asked skill's link to the profile;
  - `profile_skills`: the profile's skills and their levels;
  - `recommendations`: the Insights ranking of postings and of skills to gain, with the workplace filter.
- **Sharing is opt-in, by scope, at start-up.** `--share postings`, `--share profile` or `--share postings,profile` names what the client may receive; a tool outside the named scopes isn't offered. Without `--share` the command refuses to start and says why. There is no default, no environment variable and no "all".
- **Some data is never returned, whatever is shared:** profile details (name, headline, contact details, summaries, goals), records and highlights, documents, notes, contacts, application events, saved CVs, captured files and model output that failed verification. Nothing of a record whose effective disclosure is private can reach a result.
- **No writes of any kind.** The server opens the database read-only, never migrates it (a database not at the current schema is refused), queues no model work, calls no model and listens on no port. Tools that write (rating a posting, adding a profile skill, queueing an extraction) are out of scope; they are named as a possible later change.
- With tracing on (`--otlp-endpoint`, as on `serve` and `eval`), each tool call is one span carrying the tool's name, counts and sizes, and no text. `--trace-content` adds the call's arguments; a tool's result is never put in a span.
- `docs/mcp.md` explains the scopes, what a client can do with what it receives, how to connect a client, and how to try the server on the demo database first.
- **A fully local set-up comes first.** `docs/mcp.md` gives a worked example, run and checked when implementing, of an MCP client on this machine whose model is a local Ollama model, so tool results never leave the machine. It is the first way of connecting the page shows, before any client that may use a cloud model, and the refusal message, `jobhunt mcp --help` and the README point to it.

## Capabilities

### New Capabilities
- `mcp-server`: the read-only MCP server: how it starts, what must be named before anything is shared, which tools each scope offers and what they return, what is never returned, and that it writes nothing and contacts nothing.

### Modified Capabilities
- `model-tracing`: the trace endpoint and content options also apply to `jobhunt mcp`; MCP tool calls become the one kind of work that emits a span without calling a model; and the no-text rule is extended to tool arguments and results.

## Parser impact

None: see [parser-impact.md](parser-impact.md).

## Impact

- **Code:** new `mcp_tools.py` (the five tools as plain functions over `queries` and `recommend`, the scopes and the field lists; no `mcp` import) and `mcp_server.py` (the only module that imports `mcp`); a read-only engine in `db.py`; a tool-call span helper in `enrich/tracing.py`; the `mcp` command in `cli.py`. No change to `queries.py`, `recommend.py`, `userdata.py` or the web interface.
- **Dependencies:** optional extra `mcp` (the `mcp` SDK, which brings `pydantic`, `anyio` and `opentelemetry-api` with it). No new required dependency.
- **Data:** no schema change, no migration, and no table gains a writer.
- **Privacy:** the rule "no data leaves the machine" is restated: jobhunt itself still sends data to no other machine, and `jobhunt mcp` gives the scopes named at start-up to the program that started it. CLAUDE.md, the README and `docs/architecture.md` say so. Since jobhunt can't see where a client sends results, the project supports keeping them local the way it can: by documenting, first and with a checked example, a client that uses a local Ollama model.
- **Docs and CI:** `docs/mcp.md` (with the fully local example), a tool-span section in `docs/tracing.md`, CLAUDE.md, and the `mcp` extra installed in the CI test jobs so the protocol tests run.
