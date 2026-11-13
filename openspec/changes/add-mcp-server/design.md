## Context

See proposal.md for the motivation. What exists today, as far as it shapes the design:

- **Read models:** `queries.posting_list(conn, ListFilters)` returns every matching posting (no SQL limit; the page shows them all), with triage, tags and application status; `queries.posting_detail(conn, job_id)` returns the posting, its latest snapshot, details, triage, tags, dismissals and application, or `None`; `recommend.posting_summary(conn, job_id)` returns the score and the Have / Don't have lists; `queries.effective_links(conn, keys)` the link of each posting skill; `queries.profile(conn)["claims"]` the profile page's skills grouped by level, highest first, each with its name, `level_origin` and aliases (beside the records and highlights the page also shows); `recommend.recommendations(conn, workplaces)` both Insights lists, already capped (`TOP_POSTINGS` 20, `TOP_SKILLS` 15). None of them writes, calls a model or needs Flask.
- **URL parsers aren't validators:** `ListFilters.from_args` and `recommend.workplace_choice` silently fall back to the default on an unknown value. That suits a URL; for a tool it would turn a misspelt filter into a wrong answer.
- **Disclosure:** `queries.profile` computes each record's `effective_disclosure` (private when the record, or any record it is part of, is private). `tailor.py` drops private records before anything else and flags highlights that mention one (`private_needles`, `private_mention`). Claims carry no disclosure.
- **Opening a database:** `db.make_engine` creates a missing SQLite file's folder, and `init_db` migrates to head on every `import` and `serve`. `privacy.open_database` opens SQLite with `mode=ro` and `privacy.database_terms` refuses a database that isn't at head; on Postgres it uses an ordinary engine.
- **Tracing:** `enrich/tracing.py` is the only importer of `opentelemetry`, keeps its own provider and never sets the global one. A run handle's `set()` accepts only the keys of `RUN_ATTRIBUTES`, so no text can be attached by a new keyword. `cli._tracing_args` adds `--otlp-endpoint` (loopback only) and `--trace-content` to `serve` and `eval`.
- **The SDK** (`mcp` 2.3.0 on PyPI when this was written; Python 3.10+): `from mcp.server import MCPServer`; a tool is a decorated function whose signature is its input schema and whose return annotation is its output schema; arguments are checked against the schema before the function runs; `mcp.run()` serves over stdio and keeps stdout for the protocol; `from mcp import Client` connects to a server object in memory (`Client(server)`) or starts one as a subprocess over stdio. The SDK depends on `opentelemetry-api` and wraps every message in a span of its own, which is a no-op while no OpenTelemetry provider is configured.

## Goals / Non-Goals

**Goals:**

- Nothing reaches a client unless the user named it when starting the server, and some data can't be named at all.
- The tools answer with the figures the pages show, by calling the same read models, so there is one place to change a score or a ranking.
- Every guarantee (no writes, no network, nothing private, nothing unshared) is a test that fails when it is broken, not a statement in the docs.
- The tools are testable without the `mcp` package, and the protocol layer without a subprocess, a network or Ollama.

**Non-Goals:**

- Tools that write or start model work (see "Later changes").
- A network transport (Streamable HTTP, SSE). A listening port needs authentication and the Host and Origin checks `web/guard.py` gives the web interface.
- MCP resources, prompts, sampling or elicitation (D8).
- Telling a local client from a cloud one, or controlling what a client does with a result.
- New read models, new filters, or changes to scores, ranking or links.

## Decisions

### D1. Privacy: a scoped opt-in at start-up, over a fixed floor

**The problem.** An MCP client puts tool results into a model's context, and that model is often a cloud service. jobhunt cannot see which: over stdio it sees a pipe, the client's name in the protocol is self-reported, and a client on this machine can front a model that isn't. So the server can't enforce "stays on this machine". It can decide what is on offer and make the user decide that it is.

**The three options, each alone:**

| Option | What it gives | What it leaves open |
|---|---|---|
| A documented warning | The user knows what a client can do with results. | Data flows by default. A stdio server's stderr goes to a client log few people read, and a docs page is read once or not at all. |
| Limiting which fields are returned | The worst case is bounded whatever the client or its configuration, and the bound is testable. | Consent: what remains still flows by default. Limiting far enough to be harmless (no profile, no triage) removes the reason for the server. |
| An explicit opt-in at start-up | Nothing flows until the user says so, and the decision sits in the client's configuration where it can be read later. | One yes or no shares everything or nothing, and a yes can be copied from an example without thought. |

**Recommendation: all three, each for the part it is good at.** The opt-in decides *whether* anything is shared, scopes and a fixed floor decide *what*, and the warning says *what that means*, placed where the decision is made.

**The rule, restated.** "No data leaves the machine" becomes two statements that stay true: jobhunt itself sends data to no other machine (its model work still goes to a local Ollama only, and the MCP server calls no model); and `jobhunt mcp` gives the scopes named at start-up to the program that started it, which may send them on.

**The opt-in.** `jobhunt mcp --share SCOPE[,SCOPE...]`, required.

- No `--share`: exit 2 before the database is opened, with a message that says tool results go to the program that starts the server, that this program may send them to a model outside this machine, and what each scope holds.
- No default scope, no environment variable, no `all`. A variable exported once in a shell profile would opt every later start in silently (the reasoning that keeps `OTEL_EXPORTER_OTLP_ENDPOINT` from turning tracing on), and an argument is as easy to write in a client's configuration. Without `all`, a later change that adds a scope can't widen a configuration written before it.
- Fixed at start-up like the Ollama address and the trace endpoint: no tool, no protocol message, no setting and no web request changes it.
- At start-up the server writes one line to stderr naming the scopes and the database.

**The scopes.** A scope is a set of tools; a tool outside the named scopes isn't registered, so the client never lists it and can't call it. That is simpler than registering every tool and refusing per call: there is no per-call check to get wrong, and the client's model isn't shown a tool it would only be refused by.

| Scope | Tools | What a client can receive |
|---|---|---|
| `postings` | `search_postings`, `get_posting` | Each stored posting's latest captured fields and original URL, when it was first and last seen, and the user's triage of it: interest, fit, tags, whether it is dismissed, the application's status. |
| `profile` | `posting_fit`, `profile_skills`, `recommendations` | The profile's skill names, levels and aliases; for a posting, the skills it asks for (the user's marks and verified suggestions), their credit and link, and the match score; the Insights ranking. Each posting named carries its id, title, company and original URL. |

`profile` doesn't need `postings`: a client with `profile` alone finds posting ids in `recommendations`.

**The floor.** Whatever is shared, no tool returns: profile details (name, headline, contact details, summaries, goals); records (titles, organisations, dates, lines, sources) and ground quotes; highlights; documents and their names; a posting's notes, dismissal reasons and skill-mark quotes; application events, notes, contacts and company data; saved CVs; captured files, earlier snapshots and volatile details; suggestions that failed verification; settings, the queue, evaluation data and trace ids. Nothing in the five tools needs these: finding a posting, judging fit and choosing what to learn use skills and levels, not identity or CV text.

**The warning** appears in the refusal message, in `jobhunt mcp --help`, in the first paragraph of `docs/mcp.md` and in the README's line about the server. `docs/mcp.md` also says to try the server on the demo database first (`jobhunt demo`), where everything is fictional.

*Alternatives considered:*

- **Default to `postings` when `--share` is missing.** Which postings were saved and how they were rated is the user's data too; a default shares without a decision.
- **Refuse cloud clients, or allow clients by name.** The name is self-reported and says nothing about the model behind it.
- **Pseudonymise results** (replace company names, drop URLs). It breaks the rule that a posting always carries its original URL, and most of the use.
- **Ask per call through the protocol** (elicitation). Client support is uneven, and clients already ask the user before a tool runs; the server's part is what is on offer.
- **A setting on `/settings`.** A browser request must not be able to widen what leaves, as with the trace endpoint.
- **An audit row per call in the database.** It is a write. Tracing (D7) is the record for those who want one.

### D2. Read-only, in three layers

1. **The command never migrates.** `cli._mcp` doesn't call `init_db`. It compares `migrate.current_revision` with `migrate.head_revision` and exits 2 when they differ, with `privacy.database_terms`' message ("run `jobhunt import` or `jobhunt serve` once to upgrade it"). A missing SQLite file is an error (exit 2), and the file and its folder are not created.
2. **The database refuses writes.** New `db.read_only_engine(url)`: for SQLite, `sqlite:///file:<absolute path>?mode=ro&uri=true`, as `privacy.open_database` builds it; for Postgres, the ordinary engine with `default_transaction_read_only=on` set on every connection. So a write attempted by any code under a tool fails in the database on both backends. `privacy.py` keeps its own opener; aligning the two is not part of this change.
3. **Tools call read models only.** `mcp_tools.py` imports `queries` and `recommend`, and not `userdata`, `store`, `enrich.derived`, `enrich.jobs` or `prune`. A test checks the module's imports, and another runs every tool on a read-only engine.

Each tool call opens its own connection (`engine.connect()`), as a page view does, so a tool is safe whether the SDK runs it on the event loop or on a worker thread.

A relative `--db` (the default `sqlite:///data/jobhunt.db`) resolves against the directory the *client* starts the server in. With layer 1 that fails loudly instead of creating an empty database somewhere; `docs/mcp.md` tells the user to give an absolute path.

### D3. Two modules; only one imports `mcp`

| Module | Holds | Imports |
|---|---|---|
| `src/jobhunt/mcp_tools.py` | The five tools as plain functions `tool(conn, **arguments) -> dict`; `SCOPES` (scope → tool names); the result types (`TypedDict`); the limits; `NotFound`. | `queries`, `recommend`. No `mcp`, no Flask. |
| `src/jobhunt/mcp_server.py` | `build(engine, scopes) -> MCPServer`: one typed wrapper per shared tool, each opening a connection and a span around the plain function; the server's fixed instructions; `serve(engine, scopes)`, which runs it over stdio. | `mcp` (the only importer), `mcp_tools`, `enrich.tracing`. |

`cli.py` imports `mcp_server` inside `_mcp`, after the argument checks; an `ImportError` there prints `error: the MCP server needs the mcp extra (pip install -e ".[mcp]")` and exits 2. Unlike tracing, which is an addition to a command that works without it, this command is nothing without its package, so it stops instead of warning.

The extra is `mcp = ["mcp>=<the version pip resolves when implementing>"]`. `MCPServer` is the SDK's high-level server: schemas come from signatures, and it validates arguments and results. The SDK's low-level `Server` would mean writing JSON Schemas by hand for no gain.

- **stdout is the protocol.** Everything `cli._mcp` prints (the sharing line, the database, the tracing lines, errors) goes to stderr. The SDK redirects stray prints to stderr while serving; before that, nothing may reach stdout.
- **Logging.** `MCPServer` configures the root logger at construction (`log_level`, default `INFO`); it is built with `log_level="WARNING"`. The SDK logs an unexpected exception's traceback to stderr, which stays on this machine in the client's log.
- **The server's instructions** (sent once when a client connects) are a constant: what the tools cover, that ids are jobhunt's posting ids, that scores and rankings are jobhunt's own and aren't to be recomputed, and that a posting is cited with its original URL. No user data.

*Alternative considered:* a package `jobhunt/mcp/`. A package named like the SDK invites `import mcp` mistakes; two flat modules mirror `recommend.py` and `tailor.py`.

### D4. Tool arguments and results

Common rules:

- **Ids.** A posting is its integer `job_id`, the same number as in `/postings/<id>`. It is the only id a tool takes. Skills are returned by name; no tool takes a skill, so no skill id is exposed until one does.
- **Every posting in every result** carries `job_id`, `title`, `company` and `url` (the original posting), following the project's rule for output.
- **Results are one JSON object** with a declared output schema (the wrapper's return annotation, a `TypedDict` from `mcp_tools.py`), which the SDK returns as structured content and as JSON text. Dates are ISO 8601, times in UTC. A field with no value is left out, not sent as null, to keep results small.
- **Fields are picked by name.** A tool builds each object from named fields of the read model's row, never by passing the row through, so a column added to a read model later doesn't reach a client unnoticed.
- **Enumerations come from the read models' own tuples** (`SORTS`, `DISMISSED_MODES`, `WORKPLACE_TYPES`, `STATUS_FILTERS`), so the input schema lists the allowed values and the SDK refuses any other before the tool starts. This replaces the silent fallback of `ListFilters.from_args` and `workplace_choice`, which the tools don't call: they build `ListFilters(...)` and the `frozenset` directly from checked arguments.
- **Limits** are constants at the top of `mcp_tools.py`: `SEARCH_LIMIT_DEFAULT = 20`, `SEARCH_LIMIT_MAX = 50`, `DESCRIPTION_LIMIT = 20_000` characters.

| Tool | Arguments | Result |
|---|---|---|
| `search_postings` | `q` (text in title, company or description, or an exact external id), `tag`, `min_interest` (1–5), `unrated`, `workplace`, `status` (`any`, `none` or an application status), `dismissed` (`hidden` by default, `included`, `only`), `sort` (`last_seen` by default, `first_seen`, `posted`, `interest`), `limit` (1–50, default 20), `offset` (default 0) | `total` (matches), `offset`, `next_offset` (when more remain), `postings`: each `job_id`, `title`, `company`, `url`, `location`, `workplace_type`, `posted_on`, `first_seen`, `last_seen`, `interest`, `fit`, `tags`, `dismissed`, `application_status` |
| `get_posting` | `job_id` | The list fields, plus `source`, `employment_type`, `posted_precision`, `snapshots` (how many versions are stored), `details` (the latest snapshot's compared details), `description` (plain text), `description_chars` and, when the text was cut at the limit, `description_truncated` |
| `posting_fit` | `job_id` | `job_id`, `title`, `company`, `url`, `score` (absent when the posting has no skills), `skills`, `unlinked`, `has_profile_skills`; `have`: each `name`, `importance`, `source` (`mark` or `suggestion`), `credit`, `profile_skill`, `level`, `relation`, `link_source` (`user`, `same` or `model`); `dont_have`: each `name`, `importance`, `source`, `reason` (`missing`, `not-judged` or `no-link`) and, for `missing`, `profile_skill`. Both lists in the summary's order: required, preferred, unspecified |
| `profile_skills` | none | `count`, `skills`: each `name`, `level`, `level_origin`, `aliases`; highest level first, then by name |
| `recommendations` | `workplace` (a list of workplace types; empty or all three means no filter, as on Insights) | `workplaces` (the filter applied, absent when none), `considered`, `no_skills`, `has_posting_skills`, `has_profile_skills`; `postings`: each `job_id`, `title`, `company`, `url`, `workplace_type`, `interest`, `score`, `value` (score × interest factor), `gaps` (each `name`, `importance`, `credit`); `skills`: each `name`, `level` (a profile skill below `proficient`) or none (not in the profile), `also`, `gain`, `improved`, `postings` (each `job_id`, `title`, `company`, `url`, `rise`) |

Notes:

- **Paging is `limit` and `offset` on `search_postings` only.** `posting_list` returns every match, so the tool slices in Python, as the page renders all rows; `total` lets a client know what it hasn't seen. The protocol's own cursors page lists of tools, not tool results. `recommendations` returns what the read model returns, already capped. `profile_skills` returns every claim (see Risks).
- **The list's `labelled` filter is left out.** It selects on evaluation labelling, which no result shows.
- **The description is the snapshot's plain text**, not its HTML: smaller, and markup is no use to a model. A description over the limit is cut and flagged; no offset is offered until a real posting needs one.
- **`posting_fit` is `posting_summary` plus the link's source** from `effective_links` for the same keys. The profile skill named in `have` is the one the credit comes from, as on the posting page.
- **`profile_skills` reads the claims of `queries.profile`**, the one read model that has aliases, and picks the claim's name, level, origin and aliases. That read model also loads records and highlights for the page; the tool takes none of them (D5).

### D5. Never-returned data and private records

The floor of D1 is kept by construction (D4: fields picked by name, and no result type has a field for profile details, records, highlights, documents, notes or events) and checked by one test, in the manner of the tracing content test: a database with a marker string in every never-returned field, every tool called with a spread of arguments under both scopes, and no marker in any result. The same test asserts that markers in shared fields (a title, a tag, a skill name) *are* returned, so it can't pass by returning nothing.

**Private records.** No tool in this change returns any record, public or private: not a title, organisation, date, line or source, and not a ground's quote. So the rule "records whose effective disclosure is private are never returned" holds in its strongest form, with nothing to filter, and the marker test plants a private record and a record that is private only through its context to prove it.

A **claim** is returned whatever grounds it, including a claim whose only grounds are private records: a claim is the user's statement of a level, not a record, and the match score already counts it everywhere. This matches `tailor.py`, where a private record can't be printed or close a gap but the skill still counts toward the score.

A later tool that returns evidence (the records or highlights behind a claim) must drop records by `effective_disclosure` before anything else and apply `tailor.private_mention` to highlight text, as the CV proposal does; the `mcp-server` spec states the rule so that it binds such a tool.

### D6. Errors

| Case | What the client gets | Span |
|---|---|---|
| A posting id that doesn't exist | A tool error, "No posting with id 12." (`mcp_tools.NotFound`, turned into the SDK's `ToolError` by the wrapper) | error, `error.type` `NotFound` |
| An argument outside the schema (unknown sort, `limit` 500, a missing `job_id`) | The SDK's tool error naming the argument; the tool doesn't start | none |
| A tool outside the shared scopes, or an unknown one | The SDK's unknown-tool error | none |
| Any other exception | The SDK's generic "Error executing tool …", without the exception's message; the traceback goes to stderr | error, `error.type` the exception class |

No error message built by jobhunt quotes stored text: `NotFound` carries the id only.

### D7. Tracing: jobhunt's own span per tool call

`tracing.py` gains `tool(name, arguments)`, a context manager like `run()`:

- span name `tools/call <tool>`, kind `SERVER`, each call its own trace (no root span, as with a queue job);
- its handle's `set()` accepts only the keys of a new `TOOL_ATTRIBUTES` (as `RUN_ATTRIBUTES` does for runs), so no text can be attached by a new keyword;
- with tracing off it yields the existing `OFF` handle and nothing is imported.

| Attribute | Value | From |
|---|---|---|
| `mcp.method.name` | `tools/call` | MCP semantic conventions |
| `gen_ai.operation.name` | `execute_tool` | GenAI conventions |
| `gen_ai.tool.name` | the tool's name | GenAI conventions |
| `network.transport` | `pipe` | stable conventions (stdio) |
| `jobhunt.posting.id` | the `job_id` argument, when there is one | existing constant |
| `jobhunt.mcp.result.items` | rows in the result's main list (1 for a single posting) | the wrapper |
| `jobhunt.mcp.result.total` | `search_postings`' `total` | the wrapper |
| `jobhunt.mcp.result.chars` | length of the result as JSON text | the wrapper, only while a span is recording |
| `jobhunt.mcp.result.truncated` | true when a description was cut | the wrapper |
| `error.type` | `NotFound` or the exception class | as elsewhere in `tracing.py` |
| `gen_ai.tool.call.arguments` | the arguments as JSON, **content on only** | GenAI conventions (opt-in there too) |

The result is never put on a span, with content on or off: it is the largest and most personal thing the server handles, a viewer would become a second copy of the profile, and its size and counts answer "what did the client get". The search text and tag are text, so they appear only inside the arguments with content on. With content on, a failed span also carries the error message, as today.

`mcp.session.id`, `mcp.protocol.version` and `jsonrpc.request.id` are left out: the wrapper sits inside the tool call and doesn't see the protocol message. The convention names are constants in `tracing.py` with the others, checked against the semantic-conventions version recorded there when implementing.

**Not the SDK's spans.** The SDK's own middleware would emit a span per protocol message through OpenTelemetry's global provider. `tracing.py` never sets that provider, so those stay no-ops, and jobhunt's span is the only one exported. Using the SDK's spans instead would mean setting the global provider (which `tracing.py` avoids so tests don't depend on order), accepting attributes and status text chosen by the SDK and free to change with its version, and spans for `initialize` and `tools/list` that nobody asked for. A test asserts that a tool call exports exactly one span. For the same reason a client's trace context isn't continued: the server's spans are jobhunt's own traces, sent to this machine's viewer only.

**Options.** `cli._tracing_args(mcp)` adds `--otlp-endpoint` and `--trace-content` unchanged, with the same loopback check. `_mcp` calls `tracing.setup` after the database checks and its `shutdown` in `finally`, and writes the `tracing:` and `span content: on` lines to stderr. The `mcp` extra installs `opentelemetry-api` but not the SDK, so an endpoint without the `otel` extra still gives today's warning and no tracing.

### D8. Tools only: no resources, no prompts

- **Resources** (a posting as `jobhunt://postings/12`) would duplicate `get_posting` with a second path to keep inside the scopes, the floor and the size limit; they are attached by the user in the client, which fewer clients support than tools; and nothing in the scope needs them.
- **Prompts** (a ready-made "assess my fit for this posting") would put wording into jobhunt that nothing measures, while the project's habit is to measure prompts before adopting them.
- **Sampling and elicitation** would have the server ask the client's model or user for something; the server asks for nothing.

Each can be added later without changing a tool.

### D9. Tests, and a real client

| Layer | File | Needs | Checks |
|---|---|---|---|
| Tools as functions | `tests/test_mcp_tools.py` | nothing beyond `dev`; both backends through the `engine` fixture | Each tool against its read model on the same database (same rows, order, score, ranking); every filter; paging and `total`; the description limit; `NotFound`; `SCOPES`; the marker test (D5); every tool on a read-only engine; a write on that engine fails on both backends; the module's imports (D2); every tool with `urllib.request.urlopen` made to fail |
| Protocol, in memory | `tests/test_mcp_server.py` | the `mcp` extra (`pytest.importorskip`); anyio's pytest plugin, which the SDK installs | Through `Client(server)`: the tools listed for each `--share` value, with input and output schemas; a call's structured content equals the plain function's result; the D6 cases, including that a refused argument never starts the tool and that an unexpected exception's message isn't sent |
| Tool spans | `tests/test_mcp_tracing.py` | both extras; the `traced` and `traced_content` fixtures | One span per call with the D7 attributes; exactly one span exported per call; no marker, search text or tag on a span by default; arguments with content on and no result either way; nothing exported with tracing off; the same result with tracing on and off |
| The command | `tests/test_cli_mcp.py` | the extra only for the last check | Exit 2 and nothing opened for: no `--share`, an unknown scope, a remote trace endpoint, a missing SQLite file (still missing afterwards), a database not at head (unchanged afterwards), the package missing (import made to fail); `JOBHUNT_MCP_SHARE` in the environment changes nothing; and one round trip with the SDK's client starting `python -m jobhunt.cli mcp` as a subprocess over stdio: connect, list tools, call `search_postings`, read the sharing line on stderr |
| The demo | `tests/test_demo.py` | as today | Every tool answers on the demo database, so a change that breaks a tool on realistic data fails the suite |

No test uses a network or Ollama: the in-memory client has no transport, the subprocess test uses pipes, and no tool is given an Ollama client.

**A real client, by hand** (a task, recorded in this file as add-otel-tracing's viewer check was), always against the **demo** database:

1. The MCP Inspector, which is a client with no model: connect, list the tools for each `--share` value, call each tool.
2. Only after the user agrees, since it runs a model: one assistant client, one question per tool, with `--otlp-endpoint` pointing at a local Jaeger, to see that the answers cite original URLs and that each call is one span with no text. If that client's model is a cloud one, the only data it receives is the demo's fictional data.

The user's own database is not used for verification.

### D10. Docs

- `docs/mcp.md`: the warning first; the scopes and the floor; the tools with their arguments and one example result each (the demo's data); connecting a client (the command and arguments a client's configuration needs, with an absolute `--db`); trying it on the demo; tracing tool calls; that the server never changes the database and what to do when it refuses one.
- `docs/tracing.md`: a "Tool calls" section with the D7 table.
- CLAUDE.md: the extra and the SDK under Libraries; the two modules in the architecture; a short "MCP server" section (scopes, the floor, read-only layers, the tracing helper); the restated rule under Models; the command and install line under Commands.
- README and `docs/architecture.md`: the server in one paragraph, and the sentence "no data leaves the machine" replaced by the two statements of D1.

## Risks / Trade-offs

- **A client sends the profile to a cloud model.** → That is the user's decision, made by naming `profile`; the floor keeps identity, CV text and notes out whatever is named; the docs say it first and point to the demo.
- **A `--share` copied from an example without thought.** → The scopes are words that say what is shared, there is no `all`, and the example in `docs/mcp.md` uses the demo database.
- **A posting's description is text from outside.** It could contain instructions aimed at a model. → The server can't judge that; with this change a client can do nothing through jobhunt but read. It becomes a real question for any later tool that writes, and "Later changes" says so.
- **The SDK changes** (its second major version is months old; the middleware path is marked provisional). → A lower bound from the version installed when implementing, `mcp` imported in one module, the plain functions and their tests independent of it, and CI running the protocol tests.
- **The extra is heavy** (`pydantic`, `anyio`, an HTTP stack the server never uses). → It is optional, and nothing else imports it.
- **"Tracing off creates no spans" and the SDK.** With `mcp` imported and no trace endpoint, the SDK still calls the OpenTelemetry API for each message; with no provider configured these are no-op objects, and nothing is recorded or sent. The existing requirement is read as "records no spans and contacts no address", which the tracing-off test checks for `jobhunt mcp` too. `serve`, `eval` and `import` never import `mcp`, so nothing changes for them.
- **A large profile makes `profile_skills` large.** A few hundred claims with aliases is still a small result; paging is added when a real profile needs it.
- **`posting_list` loads every match to return twenty.** → Fine at this scale and the same cost as the page; a SQL limit belongs in the read model if it is ever needed.
- **Two commands on one SQLite file** (`serve` writing, `mcp` reading). → SQLite allows it; a read that meets a write lock waits like any other connection.

## Migration Plan

No schema or data migration. Existing installs are unaffected until they install the extra and start the command. Rollback is removing the command or the extra; nothing was stored.

## Later changes

Named so their absence here is a decision, not an oversight:

- **Tools that write:** rating or tagging a posting, dismissing one, answering "have it" for a skill, queueing an extraction. Each would go through `userdata.py` or `enrich/jobs.py`, the only writers; need a write scope of its own that no read scope implies; need an origin for what a client wrote; and need an answer to instructions hidden in posting text, since a client that reads a posting could then be steered into changing data.
- **Evidence:** the public records and highlights behind a claim, as a third scope, with the disclosure rule of D5.
- **Resources and prompts** (D8), and a network transport with authentication.

## Open Questions

- Whether `jobhunt.mcp.result.chars` should become an estimate of tokens. Characters are exact and need no tokenizer; a later change can add an attribute without touching the tools.
- Whether a cut description needs an `offset` on `get_posting`. No stored posting is expected to reach the limit; the flag will show if one does.
