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

**The warning** appears in the refusal message, in `jobhunt mcp --help`, in the first paragraph of `docs/mcp.md` and in the README's line about the server. Each of them also points to the fully local set-up below (the refusal message and `--help` by naming the section of `docs/mcp.md`), so the place where the user decides to share is also where they learn they needn't share with a cloud model at all. `docs/mcp.md` also says to try the server on the demo database first (`jobhunt demo`), where everything is fictional.

**The local path.** The server can't enforce where results go, but the project can make the private choice the easy one. This is the first feature whose output may leave the privacy-checked app, so `docs/mcp.md` leads with a set-up in which nothing does: an MCP client on this machine whose model runs on a local Ollama server, the same kind of server jobhunt's own model work uses. With it, the two statements of the restated rule collapse back into one: no data leaves the machine. The docs present it as the recommended way to connect, give it as a worked example that was run as written (D10), and introduce cloud-backed clients only after it, with the warning repeated. The example is documentation, not code: jobhunt still neither knows nor checks which client started it, and nothing in the server changes with the client.

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
- **The server's instructions** (sent once when a client connects) are a constant: what the tools cover, that every stored posting is one the user saved, that ids are jobhunt's posting ids and never the number in a posting's URL, that `interest` and `fit` are the user's ratings, that scores and rankings are jobhunt's own figures, and that `url` is a posting's original address. No user data.
- **Tool descriptions repeat what applies to each tool** (`mcp_server.DESCRIPTIONS`, built from shared sentences, and the argument descriptions). The protocol leaves it to the client whether its model sees the instructions, and ollmcp 0.35.1 never reads them: it sends Ollama only each tool's name, description and input schema (found in the 9.2 runs, below). So the descriptions state where a `job_id` comes from and that `search_postings` finds one by title, company or the number in a URL, that `interest` and `fit` are the user's ratings, that figures are jobhunt's own, that `url` is the original address, and, for `search_postings`, how `q` is matched and that `workplace` is one value. The instructions stay, for clients that use them. Neither holds stored data, and tests check both that and that each sentence reaches every tool it applies to.
- **Facts, not instructions** (2026-11-14, the user's principle). The server supports the model that uses it; it doesn't give it instructions or advice. Descriptions and results state facts about the tools and the data and never tell the model what to do (cite, report as given, don't recompute, set only the filters asked for, never combine title and company), because advice tuned to one small model may not help another, larger ones included. Warnings already fit: they say what was ignored and that a default was used. The first descriptions were instructions; they were restated as facts, and each restatement was measured (D9, "Measured wording"). `tests/test_mcp_server.py` keeps instruction phrases out of every description (`INSTRUCTING`). The instruction-style `q` rule ("put either a title or a company in `q`, never both") worked, and its first factual restatement didn't; the one adopted names no example values, after examples were measured to be copied. The user kept the option of treating an input constraint as part of the schema, or of allowing a measured exception, if no factual wording had worked.

*Alternative considered:* a package `jobhunt/mcp/`. A package named like the SDK invites `import mcp` mistakes; two flat modules mirror `recommend.py` and `tailor.py`.

### D4. Tool arguments and results

Common rules:

- **Ids.** A posting is its integer `job_id`, the same number as in `/postings/<id>`. It is the only id a tool takes. Skills are returned by name; no tool takes a skill, so no skill id is exposed until one does.
- **Every posting in every result** carries `job_id`, `title`, `company` and `url` (the original posting), following the project's rule for output.
- **Results are one JSON object** with a declared output schema (the wrapper's return annotation, a `TypedDict` from `mcp_tools.py`), which the SDK returns as structured content and as JSON text. Dates are ISO 8601, times in UTC. A field with no value is left out, not sent as null, to keep results small.
- **Fields are picked by name.** A tool builds each object from named fields of the read model's row, never by passing the row through, so a column added to a read model later doesn't reach a client unnoticed.
- **Enumerations come from the read models' own tuples** (`SORTS`, `DISMISSED_MODES`, `WORKPLACE_TYPES`, `STATUS_FILTERS`), so the input schema lists the allowed values, and any other is left out with a warning naming the argument and the allowed values (D6). This replaces the silent fallback of `ListFilters.from_args` and `workplace_choice`, which the tools don't call: they build `ListFilters(...)` and the `frozenset` directly from checked arguments.
- **Limits** are constants at the top of `mcp_tools.py`: `SEARCH_LIMIT_DEFAULT = 20`, `SEARCH_LIMIT_MAX = 50`, `DESCRIPTION_LIMIT = 20_000` characters.

| Tool | Arguments | Result |
|---|---|---|
| `search_postings` | `q` (text in title, company or description, or an exact external id), `tag`, `min_interest` (1–5), `unrated`, `workplace`, `status` (`any`, `none` or an application status), `dismissed` (`hidden` by default, `included`, `only`), `sort` (`last_seen` by default, `first_seen`, `posted`, `interest`), `limit` (1–50, default 20), `offset` (default 0) | `total` (matches), `filters_used` (the filters that left postings out, by argument, with the default `dismissed: hidden`; absent when none), `total_without` (for each of those, the matches with it alone removed), `offset`, `next_offset` (when more remain), `postings`: each `job_id`, `title`, `company`, `url`, `location`, `workplace_type`, `posted_on`, `first_seen`, `last_seen`, `interest`, `fit`, `tags`, `dismissed`, `application_status` |
| `get_posting` | `job_id` | The list fields, plus `source`, `employment_type`, `posted_precision`, `snapshots` (how many versions are stored), `details` (the latest snapshot's compared details), `description` (plain text), `description_chars` and, when the text was cut at the limit, `description_truncated` |
| `posting_fit` | `job_id` | `job_id`, `title`, `company`, `url`, `score` (absent when the posting has no skills), `skills`, `unlinked`, `has_profile_skills`; `have`: each `name`, `importance`, `source` (`mark` or `suggestion`), `credit`, `profile_skill`, `level`, `relation`, `link_source` (`user`, `same` or `model`); `dont_have`: each `name`, `importance`, `source`, `reason` (`missing`, `not-judged` or `no-link`) and, for `missing`, `profile_skill`. Both lists in the summary's order: required, preferred, unspecified |
| `profile_skills` | none | `count`, `skills`: each `name`, `level`, `level_origin`, `aliases`; highest level first, then by name |
| `recommendations` | `workplace` (a list of workplace types; empty or all three means no filter, as on Insights) | `workplaces` (the filter applied, absent when none), `considered`, `considered_without` (`{"workplace": n}`, the postings considered without the filter; absent when none), `no_skills`, `has_posting_skills`, `has_profile_skills`; `postings`: each `job_id`, `title`, `company`, `url`, `workplace_type`, `interest`, `score`, `value` (score × interest factor), `gaps` (each `name`, `importance`, `credit`); `skills`: each `name`, `level` (a profile skill below `proficient`) or none (not in the profile), `also`, `gain`, `improved`, `postings` (each `job_id`, `title`, `company`, `url`, `rise`) |

Notes:

- **Paging is `limit` and `offset` on `search_postings` only.** `posting_list` returns every match, so the tool slices in Python, as the page renders all rows; `total` lets a client know what it hasn't seen. The protocol's own cursors page lists of tools, not tool results. `recommendations` returns what the read model returns, already capped. `profile_skills` returns every claim (see Risks).
- **The list's `labelled` filter is left out.** It selects on evaluation labelling, which no result shows.
- **What narrowed a search** (2026-11-14, kept by the user after D9's runs). A search that finds nothing looks the same whether the posting isn't stored or a filter hid it, and small models kept a `workplace` filter from an earlier question and concluded the posting wasn't saved. So `search_postings` states which filters applied (`filters_used`, by argument name in the tool's order, including `dismissed: hidden`, the default, which is a filter too) and, for each, how many postings match with that one removed (`total_without`; one extra `posting_list` query per filter used). These are facts about the search, not advice. `sort`, `limit` and `offset` only order or page, so they're never filters. `recommendations` does the same for its one filter (`considered_without`, right after `considered`). In `search_postings` the two fields come right after `total`, before the postings.
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
| An argument the tool doesn't have, or a value outside the schema (unknown sort, `limit` 500), beside a usable one | The tool runs without it (a default stands in for a value); the result begins with `warnings`, one sentence per argument left out | the call's span, with `jobhunt.mcp.arguments.ignored` |
| Arguments with nothing usable in them, or a missing or unusable `job_id` | A tool error naming each argument and what was wrong with it ("Nothing usable in the arguments, so search_postings did not run: …"); the tool doesn't start | none |
| A tool outside the shared scopes, or an unknown one | The SDK's unknown-tool error | none |
| Any other exception | The SDK's generic "Error executing tool …", without the exception's message; the traceback goes to stderr | error, `error.type` the exception class |

No error message built by jobhunt quotes stored text: `NotFound` carries the id only.

**Sifted arguments, not all-or-nothing** (2026-11-14, the user's decision after D9's runs). As first built, a call with any argument outside the schema was refused, so that a misspelt filter couldn't silently widen a result. But small models make arguments up: in run 98, `qwen3:14b` sent `search_postings` a right `q` with an invented `company`, and the refusal threw the right search away; the model then merged both into `q` and found nothing. So each argument is checked on its own (`mcp_server._sift`, the SDK's `validate_arguments` replaced in `_Sifted`):
- an argument the tool doesn't have, or a value the schema doesn't accept, is left out; the tool runs with the rest and the defaults; the result begins with `warnings`, one sentence each ("`company` is not an argument of search_postings, so it was ignored."; "`limit` is outside the schema (Input should be less than or equal to 50), so it was ignored, and its default was used."). The loudness the refusal gave is kept, in the result instead of an error. Warnings come first in the JSON text a client passes its model, so a small model meets them before the postings;
- a call that gave arguments with none usable is refused (the user's rule: an empty subset is not a usable call), as is one whose required `job_id` is missing or unusable; the error names each argument and what was wrong. A call with no arguments at all is not "nothing usable": `profile_skills {}` and `search_postings {}` run;
- a value is never coerced (a one-item list for `search_postings`' `workplace` is left out, not unwrapped), so every substitution is a default the warning names. The SDK's own pre-parsing still applies: a list sent as JSON text is read as the list;
- warnings quote pydantic's reason, which names what the schema accepts and never the value sent; they do name an unknown argument, which is the model's own text sent back to it;
- the advertised input schema stays strict (`additionalProperties: false`), so a client and its model are still told exactly what's valid; only the server is lenient;
- every result type has an optional `warnings` field, so the closed output schemas allow it; the plain functions in `mcp_tools.py` never set it.

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
| `jobhunt.mcp.arguments.ignored` | how many arguments the call's sifting left out (D6), when any; never their names, which are the model's text | the wrapper |
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

   *Recorded (2026-11-13, run by the user):* MCP Inspector 2.13.0 in its command-line mode (`npx @modelcontextprotocol/inspector@2.13.0 --cli … --format json`), on the demo database. Each `--share` value was started through a one-line shell script that runs `jobhunt mcp --share … --db …`, since the Inspector's v2 documentation doesn't say how a stdio server's own flags are kept from its options.
   - `tools/list --strict`: `postings` listed `search_postings` and `get_posting`, and `profile` listed `posting_fit`, `profile_skills` and `recommendations`. Both runs exited 0 with no portability findings. Every input schema had `additionalProperties: false`, the enumerations and ranges of D4, and `job_id` required. Each output schema left the optional fields out of `required`. Every tool carried the read-only annotations.
   - `tools/call`, once per tool on both scopes, with `search_postings limit=2`, `get_posting 1`, `posting_fit 1`, `profile_skills` and `recommendations` with `workplace=["Hybrid"]`. Every call returned `isError: false`. Each `structuredContent` equalled the plain function's result on the same database, compared afterwards in Python, and its text content parsed to the same JSON.
   - Refusals all exited 5:
     - `profile_skills` with only `postings` shared: the Inspector reported `tool_not_found`.
     - `get_posting 999`: `isError: true` with "No posting with id 999.".
     - `search_postings bogus=1`: `isError: true` with pydantic's `extra_forbidden` error naming `bogus` and echoing only the value sent. (Since D6's sifting, a call with only `bogus` is still refused, now with jobhunt's own message naming `bogus` without its value; with a usable argument beside it, it runs and warns.)
   - Found and fixed: the stderr start-up line printed the read-only engine's internal URL (`sqlite:///file%3A…?mode=ro&uri=true`) instead of the `--db` given. It now prints the address as given, and `test_start_up_lines_name_the_scopes_and_database` checks the exact line.
   - Not shown by this run: whether the Inspector checks `structuredContent` against the output schema, since its documentation doesn't say.
2. Only after the user agrees, since it runs a model on the user's GPU: the fully local set-up of `docs/mcp.md` (D10), configured exactly as the page writes it, one question per tool, with `--otlp-endpoint` pointing at a local Jaeger, to see that the answers cite original URLs and that each call is one span with no text. This is the run that checks the documented example; if the page's configuration needs any change to work, the page is corrected and the run repeated. No cloud-backed client is used for verification.

   *Runs so far (2026-11-13, agreed by the user; demo database, ollmcp 0.35.1, a second Ollama 0.32.1 on `127.0.0.1:11435` with `OLLAMA_NO_CLOUD=1`, Jaeger 2.23.0 on loopback; five questions, one per tool, the same in every run):*
   - Two `qwen3:8b` runs and one `qwen3:14b` run with the descriptions as first written. The page needed `--provider ollama` (else a saved cloud provider wins) and wrong wording about `/tools` fixed. Answers cited real URLs only. But models passed the number in a posting's URL as `job_id` (5 of the 6 posting_fit/get_posting attempts), kept a `workplace` filter from an earlier question, and reported the user's `fit` rating as a match score.
   - **What ollmcp sends**, read from its source and then confirmed by `scripts/ollama_capture.py` (task 9.5): the tools as `{name, description, parameters}` only (no output schema, annotations or server instructions); no system message unless the user sets one; `think: "medium"`; no `options`, so the model's default sampling and the server's context size; and, for a new question, the earlier questions and final answers only, without tool calls, results or thinking. So the instructions never reached the model, and a `job_id` from an earlier result is unavailable unless an answer repeated it. Hence D3's descriptions (task 9.4).
   - **Context.** With Ollama's default 4096 tokens, the request that writes question 5's answer overflowed: Ollama shifted the context (`truncated = 1`), dropping half of it mid-answer. That happened in the first `qwen3:14b` run, which then gave made-up fit scores, and again in the first run with new descriptions. The page now has the server run with `OLLAMA_CONTEXT_LENGTH=8192`. No later run overflowed.
   - **`qwen3:14b`, old against new descriptions** (one run each; sampling isn't fixed, so one run per variant is a sample, not a rate):

     | Question (tool) | old, 4096 | old, 8192 | new, 4096 | new, 8192 | new + "saved" on recommendations, 8192 |
     |---|---|---|---|---|---|
     | 1 remote postings (`search_postings`) | right | right | right | right | right |
     | 2 Machine Learning Engineer at Example Labs | not found | not found | not found | not found | not found |
     | 3 fit for Senior Data Analyst (`posting_fit`) | URL number as job_id | URL number as job_id | searched by URL number, right | searched by title only, gave up | searched by URL number, right |
     | 4 expert skills (`profile_skills`) | right | right | right | right | right |
     | 5 best remote fits (`recommendations`) | called, figures made up | searched with `tag: "saved"`, found none | searched instead, `fit` rating as score | searched instead, `fit` rating as score | called, figures right |

     The URL number was used as a `job_id` in both old runs and in none of the three new ones. Question 5's thinking showed why the first new descriptions lost `recommendations`: "the recommendations function might include postings not saved". "Every stored posting is one the user saved" was then added to `recommendations` too, and the next run called it. Question 2 fails in every run: the model puts title and company in one `q` (matched as one phrase, so nothing matches), despite the description saying to search for each on its own; in the old runs and the first new one it also kept `workplace: Remote` from question 1. Making `q` match words rather than a phrase would change the search's behaviour, so it's left for the user to decide.
   - **Rewording `q`'s rule** (2026-11-14, the user chose to keep phrase matching; one more `qwen3:14b` run at 8192, the setup above otherwise). The rule now leads `q`'s description and is also in search_postings' description: "`q` is one phrase, not keywords: put either a title or a company in `q`, never both (e.g. `Data Analyst`, not `Data Analyst Acme`)." The model read it: its thinking quoted it and planned to search the title alone. But it then invented a `company` argument beside `q: "Machine Learning Engineer"`, which was refused, and on the retry it put both back into one `q`, reasoning "even though the note says not to combine them, maybe the function can still process it". Nothing matched, and it said the posting wasn't saved. Both calls also kept `workplace: Remote` from question 1, and that posting is Hybrid, so even the title alone would have found nothing. Questions 1, 3, 4 and 5 were right, as in the previous run, with no context shift. So the rewording changed the model's reasoning but not its answer: a one-word phrase in `q` is still the last thing it tries, and the kept filter is a second cause.
   - **Sifted arguments** (2026-11-14, run 99; D6's "Sifted arguments", same setup and questions). The model again sent `search_postings` `q: "Machine Learning Engineer"` with an invented `company: "Example Labs"`. The server ignored `company`, warned, and found the posting; the model called `get_posting` with its `job_id` 1 and answered question 2 right for the first time, requirements and pay ($105,000–$125,000 CAD) as the posting states them. This time it didn't keep `workplace: Remote` from question 1, so that cause wasn't tested, and one run can't tell how often it will. Questions 1, 3, 4 and 5 were right, as in the two runs before; question 5 again called its gaps "missing" though some are skills the user has at a low level. Seven spans, one per call, the sifted search's with `jobhunt.mcp.arguments.ignored` 1; connections only to loopback.
   - Every run: connections only to loopback (the Ollama port or the capture proxy, Jaeger's 4318 from `jobhunt mcp`, and ollmcp's start-up version check, which in this environment goes through a loopback HTTPS proxy); one span per tool call that ran, each its own trace, no text, NotFound recorded as `error.type` with the posting id.
   - **The page as written** (2026-11-14, run 100, which completes this item): ollmcp 0.35.1 started with the page's command line exactly (`--provider ollama --host http://localhost:11434 --model qwen3:8b --servers-json …`), the page's server configuration with `--otlp-endpoint` added as its tracing section says, Ollama 0.32.1 started with the page's own command (`OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=8192 ollama serve`, on its default `127.0.0.1:11434`; this machine also needs its usual GPU variables), no saved ollmcp configuration, the same five questions. Nothing on the page needed changing. Connections: ollmcp only to `127.0.0.1:11434` and its update check (through this environment's loopback HTTPS proxy), `jobhunt mcp` only to Jaeger's `127.0.0.1:4318`; no context shift. Seven spans, one per call, whose only text values are the fixed names (tool, operation, method, transport, `NotFound`). Every link in the answers was one of the demo's posting URLs. Answers: questions 1, 3, 4 and 5 right, with the tools' figures. Question 3 first passed the URL number as `job_id` (NotFound), then searched by title with `workplace` as a list, which D6's sifting ignored with a warning, so the search found the posting; before sifting that call would have been refused. Question 2 searched by title alone, as the reworded `q` rule asks, but kept `workplace: Remote` from question 1 and found nothing; the model then described the NLP Scientist posting without reading it and gave a salary that posting doesn't state ($140,000–$160,000; the posting says $120,000–$140,000 CAD). The page's example answers come from this run, verified word for word against the terminal, and it says what went wrong in question 2 so a reader checks figures against the linked posting.

**Measured wording** (2026-11-14 and 15, agreed by the user). After run 100, each change to the descriptions or results was run as a batch of fresh sessions: `qwen3:8b`, the demo database, ollmcp 0.35.1 driven in a pseudo-terminal through `scripts/ollama_capture.py`, Ollama at 8192 tokens (no context shift in any run), and the same five questions (the remote postings; what the Machine Learning Engineer posting at Example Labs asks for and pays; the fit for Senior Data Analyst at Example Insurance; the expert skills; the best remote fits). Sampling isn't fixed, so a batch gives rates, not answers; 5 runs a stage at first, 3 later to save time. Each stage changed one thing from the one it is compared with. Question 2 is the hard one: that posting is Hybrid, so it needs one field in `q` and no `workplace` kept from question 1, then `get_posting` for the pay.

| Stage (runs) | What changed | Q2 right | All five right | Title and company in one `q` | `workplace` kept in Q2 |
|---|---|---|---|---|---|
| baseline (5) | sifting; instruction-style descriptions, `q`: "put either a title or a company in `q`, never both (e.g. `Data Analyst`, not `Data Analyst Acme`)" and "Set only the filters the user's question asks for" | 2 | 2 | 0 | 5 |
| change 1 (5) | + `filters_used`, `total_without`, `considered_without` | 4 | 2 | 0 | 5 |
| change 2 (5) | + descriptions restated as facts; `q`: "`Data Analyst` matches postings whose … description holds those two words together, and `Data Analyst Acme` only those holding all three in that order" | 0 | 0 | 4 | 3 |
| `q` single field (3) | `q`: "values that match are text from a single field, such as a title (`Data Analyst`) or a company (`Acme`) …" | 0 | 0 | 0 | 3 |
| **`q` substring (3 + 3)** | `q`: "is matched as a substring, ignoring case: a posting matches when its title, its company or its description contains the whole of `q`, exactly as written." | **5 of 6** | **4 of 6** | 2 of 6 | 6 of 6 |
| `q` separate fields (3) | `q`: "… `q` holding a title and a company together matches a posting only where its description happens to contain them written together." | 0 | 0 | 3 | 3 |
| `q` joined (3) | the substring sentence with "one field at a time" and example values | 1 | 0 | 1 | 3 |
| renamed field (3) | substring `q`; `total_without` named `total_if_removed` | 1 | 1 | 2 | 2 |
| `total_without` sentence (3) | substring `q`; "`total_without` has one entry for each filter in `filters_used`: the number of postings that would match with only that filter removed." | 1 | 0 | 1 | 3 |

What the captures showed:

- **`filters_used` and `total_without` helped** (change 1): in two runs the model's thinking quotes `total_without` and it searched again without `workplace`. Kept.
- **The `q` sentence decides whether title and company are combined, and example values are copied.** Every factual wording that showed a combined value or described the combined form (change 2, separate fields) was followed by combining, though the instruction showed the same example with "never both" and had none; the single-field wording, which never shows it, had none, but its company example was followed by an invented `company` argument in every run (sifting ignored it). Adopted: the substring sentence, which names no example values. It rests on six runs, and will be measured again by the next change.
- **The leftover `workplace` filter is unsolved.** It was kept in nearly every run of every stage. Of the substring sentence's five Q2 passes, two came from the model dropping the filter and three from sending it as a list, which sifting ignored. In the failures the model's thinking either never mentions `total_without` or reads it right and still says the posting isn't saved, so neither the renamed field nor the clearer sentence was kept: making the count easier to read doesn't help when it isn't acted on.
- **Noise.** With the `q` sentence unchanged, combining ran 2 of 6, 2 of 3 and 1 of 3, and questions 3 to 5 moved by one or two runs between stages that didn't touch them. Only large differences (0 against 3 or 4 runs) are read as effects.
- Runs, captures and the harness are under `data/mcp-smoke/` (ignored, demo data only); the next change moves the harness into the repository ("Later changes").

The user's own database is not used for verification.

### D10. Docs

- `docs/mcp.md`: the warning first, with a pointer to the local set-up; the scopes and the floor; the tools with their arguments and one example result each (the demo's data); **keeping everything on this machine** (below), as the first and recommended way to connect; connecting other clients (the command and arguments a client's configuration needs, with an absolute `--db`), introduced with the warning repeated; trying it on the demo; tracing tool calls; that the server never changes the database and what to do when it refuses one.
- **The local example** (section "Keeping everything on this machine"; the refusal message and `--help` name it, and a test checks that the heading exists in `docs/mcp.md`, so the pointer can't go stale):
  - **The client** is chosen when implementing, as one that runs on this machine, starts a stdio MCP server from its configuration, talks to Ollama at a loopback address, and works with no account. Terminal clients made for Ollama (such as `ollmcp`, from mcp-client-for-ollama, or `oterm`) and general agents with an Ollama provider (such as Goose) are the candidates to check first; a client that reaches MCP only over HTTP (a proxy such as `mcpo` in front of Open WebUI) is not used, since it would put a listening port in front of the server, which the non-goals rule out. The choice and the reason go in this file.
  - **The model** is one Ollama lists with tool support and that fits a single consumer GPU; the page names it with its tag and says that any tool-capable model can be used in its place.
  - **The page gives:** installing the client; pulling the model (`ollama pull …`); the client's configuration in full, starting `jobhunt mcp --db sqlite:////<absolute path>/demo/jobhunt.db --share postings,profile` (an absolute path to the demo database, the venv's `jobhunt` by absolute path so the client needn't activate it); which of the client's settings could send data elsewhere (cloud providers or fallbacks, telemetry, sync, update checks that carry content) and how to turn each off or confirm it is off; how to confirm the client's model address is loopback (and that it stays so if `OLLAMA_HOST` or the client's own variable is set); one question per scope with an excerpt of what the client answered, from the demo's data; and the client and model versions it was checked with, and the date.
  - **Chosen when implementing (2026-11-13): ollmcp 0.35.1 with `qwen3:8b`.** Both terminal candidates now reach cloud providers too (ollmcp with `--provider`, oterm 0.18 through pydantic-ai), so neither is local by construction; ollmcp was taken because its local use can be pinned entirely on its command line (`--host`, `--model`, `--servers-json` with the same `mcpServers` shape other clients use), its default provider is `ollama`, it doesn't read `OLLAMA_HOST` (so an exported variable can't redirect it; only `--host` or a host saved with `/save-config` can), and `/tools` lists a server's tools without a prompt. Reading its source found one outbound request besides Ollama, a version lookup to pypi.org at each start carrying no user data and with no setting to turn it off, and no telemetry; the page says both. Ollama's own `-cloud` model tags are the other way out: the page has the server run with `OLLAMA_NO_CLOUD=1` and the client always given `--model`, since without it ollmcp takes the first model Ollama lists. Goose wasn't needed once ollmcp fit. The configuration was checked by calling ollmcp's own `ServerConnector.connect_to_servers` on the page's file (pointed at the demo): it started `jobhunt mcp`, listed the five tools and loaded no model, with Ollama not running. It reported "jobhunt has resources capability but returned none": `MCPServer` advertises the resources and prompts capabilities with empty lists, which offers none, as the spec requires.
  - **What the page says it does and doesn't guarantee:** with this set-up nothing leaves the machine; jobhunt doesn't check that the client is configured so, and a later change to the client's configuration or defaults can undo it.
- `docs/tracing.md`: a "Tool calls" section with the D7 table.
- CLAUDE.md: the extra and the SDK under Libraries; the two modules in the architecture; a short "MCP server" section (scopes, the floor, read-only layers, the tracing helper); the restated rule under Models; the command and install line under Commands.
- README and `docs/architecture.md`: the server in one paragraph, and the sentence "no data leaves the machine" replaced by the two statements of D1.

## Risks / Trade-offs

- **A client sends the profile to a cloud model.** → That is the user's decision, made by naming `profile`; the floor keeps identity, CV text and notes out whatever is named; the docs say it first and point to the demo.
- **The local example goes stale** (a client renames a setting, adds a cloud default or telemetry, or a model tag is retired). → The page records the client and model versions and the date it was checked; the configuration is checked against the client's own documentation when writing; and the pointer from the command is a tested heading, so at least the link can't break unnoticed. A stale example is a docs fix, not a server change.
- **A local model answers worse than a cloud one** (fewer or wrong tool calls). → The example's job is to show that the private choice works, not that it is best; the page says a larger tool-capable model can be swapped in, and the scores and rankings come from jobhunt, not the model (the descriptions state that they are jobhunt's own figures).
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
- **Measuring the descriptions** (next, agreed 2026-11-15): the smoke-test harness of D9 moves into the repository as `scripts/mcp_eval/` (demo data only; runs and captures stay in the ignored `data/`), with a request replay that samples one tool call many times from a captured prompt, a held-out set of questions no wording is tuned on, and a rule for adopting a wording. Later wording changes, such as a statement about the leftover `workplace` filter, are measured with it.
- **Naming what a filter hid**: when a search finds nothing, listing the postings that removing one filter would find (id, title, company, workplace type, url), so a model needn't act on a count. A behaviour change, left for the user to decide once the measuring change exists.

## Open Questions

- Whether `jobhunt.mcp.result.chars` should become an estimate of tokens. Characters are exact and need no tokenizer; a later change can add an attribute without touching the tools.
- Whether a cut description needs an `offset` on `get_posting`. No stored posting is expected to reach the limit; the flag will show if one does.
