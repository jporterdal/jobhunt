# The MCP server

`jobhunt mcp` lets an assistant that speaks the [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
read your stored postings, your skill profile and the match figures, so that "which of my saved postings fit me
best, and what do they still ask for?" is answered from your data instead of from what you retype.

**Read this first.** jobhunt itself sends nothing to another machine: its own model work goes to your local Ollama
server, and the MCP server calls no model at all. But the MCP server hands its results to the program that started
it, and that program puts them into a model's context. **If that model is a cloud service, whatever you share goes
to it.** jobhunt can't see which model a client uses, so it can't stop that. You decide what is shared, by naming
it when the server starts (`--share`), and you can keep everything on this machine by using a client whose model runs
on your own Ollama server: see [Keeping everything on this machine](#keeping-everything-on-this-machine), the
set-up this page recommends. Try any set-up on the demo database first ([below](#trying-it-on-the-demo)), where
everything is invented.

Install the extra once (it brings the official `mcp` SDK; nothing else in jobhunt needs it):

```bash
pip install -e ".[mcp]"
```

## What is shared

Nothing is shared until you name it. `--share` takes one or both scopes, separated by a comma; there is no
default, no environment variable and no "all", so a scope added in a later release never widens a configuration
you wrote before it.

| Scope | Tools | What a client can receive |
|---|---|---|
| `postings` | `search_postings`, `get_posting` | Each stored posting's latest captured fields and original URL, when it was first and last seen, and your triage of it: interest, fit, tags, whether it is dismissed, the application's status. |
| `profile` | `posting_fit`, `profile_skills`, `recommendations` | Your profile's skill names, levels and aliases; for a posting, the skills it asks for, their credit and link, and the match score; the Insights ranking. Each posting named carries its id, title, company and original URL. |

`profile` doesn't need `postings`: a client with `profile` alone finds posting ids in `recommendations`. A tool
outside the scopes you named isn't listed to the client and can't be called.

**Never shared, whatever you name:** your profile details (name, headline, contact details, summary, goal); records
(titles, organisations, dates, lines, sources) and ground quotes; highlights; documents and their names; a posting's
notes, dismissal reasons and skill-mark quotes; application events, notes, contacts and company data; saved CVs;
captured files, earlier versions of a posting and its volatile details; model suggestions that failed verification;
settings, the queue, evaluation data and trace ids. Nothing of a record that is private, or part of a private record,
can reach a result. A skill's level is shared whatever grounds it: it is your statement, not part of the record.

The server never changes anything: it opens the database read-only (the database itself refuses writes), never
migrates it, queues no model work, calls no model and listens on no port.

## The tools

Ids are jobhunt's posting ids, the number in a posting's page address (`/postings/3`), never the number in a
posting's original URL. Every posting in every result carries `job_id`, `title`, `company` and `url` (the original
posting). Dates are ISO 8601, times UTC, and a field with no value is left out. The examples below are from the demo
database.

Each tool's description states the facts a model needs to use the tool well: where a `job_id` comes from, that
`interest` and `fit` are the user's own ratings, that scores and rankings are jobhunt's own figures, and that each
posting's `url` is its original address. They are statements about the tools and the data, not instructions: the
server supports the model that uses it and doesn't tell it what to do, since advice tuned to one model may not help
another. The server also sends these facts as instructions when a client connects, but a client need not pass those
on to its model (ollmcp doesn't), so the descriptions don't rely on them.

### `search_postings` (scope `postings`)

The postings list with its filters, a page at a time. Arguments, all optional: `q` (text in the title, company or
description, or an exact external id), `tag`, `min_interest` (1–5), `unrated`, `workplace` (`On-site`, `Hybrid`,
`Remote`), `status` (`any`, `none` or an application status), `dismissed` (`hidden` by default, `included`,
`only`), `sort` (`last_seen` by default, `first_seen`, `posted`, `interest`; newest or highest first), `limit` (1–50,
default 20) and `offset` (default 0). How every tool treats arguments outside these is under "Arguments outside a
tool's schema" below.

`q` is matched as a substring, ignoring case: a posting matches when its title, its company or its description
contains the whole of `q` as written (or `q` is its exact external id). `Machine Learning Engineer` finds that
posting; `Machine Learning Engineer Example Labs` finds it only if one of those fields holds the whole phrase.

Besides `total`, the result names the filters that left postings out (`filters_used`, including the default that
hides dismissed postings) and, for each of them, how many postings match with that filter removed and the rest kept
(`total_without`). Both are left out when no filter was applied. So a search that finds nothing shows which filter
hid what: `q: "Machine Learning Engineer"` with `workplace: "Remote"` gives `total: 0` and `total_without`
`{"q": 4, "workplace": 1, "dismissed": 0}`, since that posting is Hybrid.

```json
{
  "total": 9,
  "filters_used": {"dismissed": "hidden"},
  "total_without": {"dismissed": 10},
  "offset": 0,
  "next_offset": 3,
  "postings": [
    {
      "job_id": 3,
      "title": "Senior Data Analyst",
      "company": "Example Insurance",
      "url": "https://jobs.example.com/view/9000000103",
      "location": "Remote",
      "workplace_type": "Remote",
      "posted_on": "2026-09-30",
      "first_seen": "2026-10-01T09:10:00+00:00",
      "last_seen": "2026-10-12T09:30:00+00:00",
      "interest": 3,
      "fit": 5,
      "tags": ["remote"],
      "dismissed": false
    }
  ]
}
```

(`limit: 3`; the other two postings are left out here.)

### `get_posting` (scope `postings`)

One posting's latest version by `job_id`: the fields above, plus `source`, `employment_type`, `posted_precision`,
`snapshots` (how many versions are stored), `details`, and `description` as plain text. A description longer than
20,000 characters is cut there, with `description_truncated: true`; `description_chars` is always the full length.

```json
{
  "job_id": 3,
  "title": "Senior Data Analyst",
  "company": "Example Insurance",
  "url": "https://jobs.example.com/view/9000000103",
  "source": "jobs.example.com",
  "employment_type": "Full-time",
  "posted_precision": "day",
  "snapshots": 2,
  "details": {"apply_method": "quick_apply"},
  "description": "About the role\nThe analytics group supports pricing and claims teams across the country.\n…",
  "description_chars": 492
}
```

(The fields `search_postings` returns are left out here.)

### `posting_fit` (scope `profile`)

A posting's match against your profile, with the same score, entries and order as the skill summary on its page:
`score` (absent when the posting has no skills), `skills`, `unlinked`, and `have` / `dont_have`. A `have` entry names
the profile skill its credit comes from, with its level, the relation and where the link came from (`link_source`:
`user` for your own link, `same` for the same skill, `model` for link judging). A `dont_have` entry gives the reason:
`missing` (linked to a profile skill at level `missing`), `no-link` or `not-judged`.

```json
{
  "job_id": 3,
  "title": "Senior Data Analyst",
  "company": "Example Insurance",
  "url": "https://jobs.example.com/view/9000000103",
  "score": 0.644375,
  "skills": 9,
  "unlinked": 1,
  "has_profile_skills": true,
  "have": [
    {"name": "PostgreSQL", "importance": "required", "source": "suggestion", "credit": 0.85,
     "profile_skill": "PostgreSQL", "level": "proficient", "relation": "same", "link_source": "same"},
    {"name": "Power BI", "importance": "required", "source": "suggestion", "credit": 0.255,
     "profile_skill": "Tableau", "level": "proficient", "relation": "related", "link_source": "user"}
  ],
  "dont_have": [
    {"name": "dbt", "importance": "preferred", "source": "suggestion", "reason": "no-link"}
  ]
}
```

(Six of the eight `have` entries are left out here.)

### `profile_skills` (scope `profile`)

Every skill in your profile with its level (`missing` < `learning` < `familiar` < `proficient` < `expert`), whether
you or a model set the level (`level_origin`), and its aliases; highest level first, then by name.

```json
{
  "count": 23,
  "skills": [
    {"name": "Forecasting", "level": "expert", "level_origin": "user", "aliases": []},
    {"name": "Python", "level": "expert", "level_origin": "user", "aliases": []}
  ]
}
```

### `recommendations` (scope `profile`)

The two lists on the Insights page, with the same members, order and figures: `postings` to look at first (score,
`value` = score × interest factor, and the largest `gaps`) and `skills` to gain (`gain`, how many postings it would
`improve`, the names pooled with it in `also`, and the postings it raises most, each with its `rise`). `workplace` is
an optional list of workplace types; empty or all three means no filter, and `workplaces` in the result names the
filter applied. With a filter, `considered_without` gives how many postings would be considered without it.

```json
{
  "workplaces": ["Remote"],
  "considered": 3,
  "considered_without": {"workplace": 7},
  "no_skills": 0,
  "has_posting_skills": true,
  "has_profile_skills": true,
  "postings": [
    {"job_id": 3, "title": "Senior Data Analyst", "company": "Example Insurance",
     "url": "https://jobs.example.com/view/9000000103", "workplace_type": "Remote", "interest": 3,
     "score": 0.644375, "value": 0.644375,
     "gaps": [{"name": "Power BI", "importance": "required", "credit": 0.255}]}
  ],
  "skills": [
    {"name": "NLP", "also": [], "gain": 0.1511111111111111, "improved": 1,
     "postings": [{"job_id": 10, "title": "NLP Scientist", "company": "Example Labs",
                   "url": "https://jobs.example.com/view/9000000110", "rise": 0.11333333333333334}]}
  ]
}
```

(`workplace: ["Remote"]`; entries are left out here.)

### Arguments outside a tool's schema

Each tool's input schema lists exactly the arguments it takes, and allows no other. Small models still make some up,
or send a value the schema doesn't allow, so the server checks a call's arguments one by one instead of refusing the
whole call:

- An argument the tool doesn't have, or a value outside the schema (a sort it doesn't know, `limit` over 50, a list
  where one value goes), is left out. The tool runs with the other arguments, and with the default for any value left
  out.
- The result then begins with `warnings`, one sentence for each argument left out, saying why and whether a default
  was used. A warning names the argument, and what the schema accepts, but never repeats the value sent.
- A call is refused, and the tool doesn't run, when it gave arguments and none of them could be used, or when
  `job_id` is missing or isn't a whole number. The error names each argument and what was wrong with it. A call
  with no arguments at all, such as `profile_skills`, runs as usual.

For example, `search_postings` with `q: "Machine Learning Engineer"` and `company: "Example Labs"` searches with `q`
alone:

```json
{
  "warnings": ["`company` is not an argument of search_postings, so it was ignored."],
  "total": 1,
  "filters_used": {"q": "Machine Learning Engineer", "dismissed": "hidden"},
  "total_without": {"q": 9, "dismissed": 1},
  "offset": 0,
  "postings": [{"job_id": 1, "title": "Machine Learning Engineer", "company": "Example Labs",
                "url": "https://jobs.example.com/view/9000000101", "...": "..."}]
}
```

With `company` alone, the call is refused: "Nothing usable in the arguments, so search_postings did not run:
`company` is not an argument of search_postings."

## Keeping everything on this machine

This is the recommended way to connect. The client below runs on this machine and its model runs on your own
Ollama server, the same kind of server jobhunt's model work uses, so no tool result leaves the machine.

It uses [ollmcp](https://github.com/jonigl/mcp-client-for-ollama) (MCP Client for Ollama), a terminal chat client
made for Ollama: it starts `jobhunt mcp` from a configuration file, needs no account, and talks to the Ollama
address you give it. The model is `qwen3:8b`, which Ollama lists with tool support and which fits a single 16 GB GPU;
any model whose `ollama show` lists the `tools` capability works in its place, and a larger one usually calls tools
more reliably. jobhunt doesn't check any of this: it is how you configure the client, and a later change to the
client's configuration or defaults could undo it.

The steps below were checked on 2026-11-14 with ollmcp 0.35.1, Ollama 0.32.1 and `qwen3:8b`, on the demo database:
the client's only connections were to Ollama on `127.0.0.1:11434` (and its update check, below), and the answers
are under [What the answers looked like](#what-the-answers-looked-like).

### 1. Keep Ollama local

Ollama binds `127.0.0.1:11434` by default; leave `OLLAMA_HOST` unset (or set to a loopback address) for the server.
Ollama can also run cloud models, whose tags end in `-cloud`: a prompt to one of those is sent to ollama.com. Turn
that off for the server by setting `OLLAMA_NO_CLOUD=1` in its environment (or `"disable_ollama_cloud": true` in
`~/.ollama/server.json`) and restarting it. Under systemd:

```bash
sudo systemctl edit ollama.service       # add under [Service]:  Environment="OLLAMA_NO_CLOUD=1"
                                         #                 and:  Environment="OLLAMA_CONTEXT_LENGTH=8192"
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

If you start the server yourself, use `OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=8192 ollama serve`.

Give the server a context of at least 8192 tokens as well, with `OLLAMA_CONTEXT_LENGTH=8192` beside
`OLLAMA_NO_CLOUD=1` (ollmcp sends no context size of its own unless you set `num_ctx` with `/model-config`). With a
4096-token context, a question whose answer draws on a long tool result, such as `recommendations`, can fill it
while the model is still answering; Ollama then drops the older half of the conversation, tool result included, and
the model finishes without it. The server's log shows `context shift` when that happens. Then pull the model:

```bash
ollama pull qwen3:8b
ollama show qwen3:8b                     # "tools" must be among its capabilities
```

### 2. Install the client

Install it in its own environment, not jobhunt's venv:

```bash
uv tool install ollmcp==0.35.1
# or, without uv:
python3 -m venv ~/.venvs/ollmcp && ~/.venvs/ollmcp/bin/pip install ollmcp==0.35.1
```

### 3. Configure the server for the client

Build the demo first (`jobhunt demo`, see [below](#trying-it-on-the-demo)), and write this file, for example as
`~/.config/ollmcp/jobhunt-demo.json`. Replace `/path/to/jobhunt` with the absolute path of your jobhunt checkout:
the client starts the server in a folder of its own, so a relative path would point somewhere else, and calling the
venv's `jobhunt` by its full path means nothing needs activating.

```json
{
  "mcpServers": {
    "jobhunt": {
      "command": "/path/to/jobhunt/venv/bin/jobhunt",
      "args": ["mcp", "--db", "sqlite:////path/to/jobhunt/demo/jobhunt.db", "--share", "postings,profile"],
      "disabled": false
    }
  }
}
```

### 4. Start it

```bash
ollmcp --provider ollama --host http://localhost:11434 --model qwen3:8b \
    --servers-json ~/.config/ollmcp/jobhunt-demo.json
```

On start it lists the five `jobhunt.*` tools under "Available Tools", before anything is sent to the model. (`/tools`
opens a selector for turning tools off; `q` leaves it.) Then ask, for example, "Which of my saved remote postings fit
me best, and what do they still ask for? Link each one."

Before each tool call, ollmcp shows the tool and its arguments and asks whether to run it (`y` runs it, `n` skips
it). That is the moment to see what the model is about to read. The result then goes to the model on your own
Ollama server.

ollmcp gives its model each tool's name, description and arguments, but not the instructions the server sends when
it connects, so jobhunt's tool descriptions repeat the facts the model needs (where a `job_id` comes from, that
scores are jobhunt's own figures, that each posting's `url` is its original address). ollmcp also has a system
prompt of its own (`/model-config`, then `sp`), which is sent to the model first in every request. It is empty unless
you set it, and `/save-config` saves it with the rest of ollmcp's settings, including the provider and host.

For each new question ollmcp sends the earlier questions and its final answers to them, but not the tool calls,
results or thinking that led to those answers. A follow-up question therefore can't use a `job_id` from an earlier
result unless an answer repeated it; the model calls a tool again instead.

### What the answers looked like

Excerpts from one session with the set-up above (`qwen3:8b`, the demo database, each tool call confirmed with `y`),
run on 2026-11-14 with an earlier version of the tool descriptions, which told the model what to do, and before
`search_postings` returned `filters_used` and `total_without`. Every "View posting" was a link to the posting's
original URL, and every figure is the tool's own. Later sessions with the current descriptions, measured in batches,
gave answers of the same kind and made the same kinds of mistakes, the leftover `workplace` filter most often.

> **Which of my saved postings are remote? List each with its title, company and link.** (scope `postings`)
>
> Here are your saved remote postings:
>
> 1 Senior Data Analyst
>   Example Insurance
>   View posting
>
> (and the other three remote postings: NLP Scientist at Example Labs, MLOps Engineer at Example Systems, Data
> Engineer at Example Payments)

> **How well do I fit the Senior Data Analyst posting at Example Insurance, and which of its skills am I missing?
> Include its link.** (both scopes: `search_postings`, then `posting_fit`)
>
> The Senior Data Analyst posting at Example Insurance (remote) matches you with a fit score of 0.644 (out of 1.0).
> Here's a breakdown:
>
> • Data visualisation (proficient, 0.85 credit) … • Python (expert level, 1.0 credit)
>
> • dbt (importance: preferred, reason: no-link)

> **Which of my saved remote postings fit me best, and what do they still ask for? Link each one.** (scope
> `profile`, `recommendations`)
>
> Here are your best-fit remote postings (ordered by weighted match score), along with the skills each still
> requires:
>
> 1. Senior Data Analyst … Fit score: 0.644 (interest: 3) … • Power BI (required, 0.255 credit) …
> 2. NLP Scientist … Fit score: 0.347 (interest: 4) …
> 3. MLOps Engineer … Fit score: 0.267 (interest: 4) …

A small model still makes mistakes the tools can't prevent, so check what matters against the linked posting. In
the same session:

- For the third question it first passed the number in the posting's URL as a `job_id` (the tool answered that no
  posting has that id), then searched by title with `workplace` given as a list. The server ignored the list, with a
  warning (see [Arguments outside a tool's schema](#arguments-outside-a-tools-schema)), and the search found the
  posting.
- Asked about the Machine Learning Engineer posting at Example Labs, it kept `workplace: Remote` from the first
  question, found nothing (that posting is Hybrid), and then described the NLP Scientist posting without reading
  it, with a salary that posting doesn't state. A larger model (`qwen3:14b`) answered the same question from the
  posting.

### What could still send data elsewhere

- **Other providers.** ollmcp can also talk to cloud providers (OpenAI, OpenRouter and others) with `--provider`
  and an API key. Pass `--provider ollama` as above: without it, ollmcp uses the provider saved in its
  configuration (by `/save-config`), which may be a cloud one. Don't pass `--api-key`, and leave `OLLMCP_API_KEY`
  unset.
- **The model.** Always pass `--model` with a local tag. Without it, ollmcp uses the model saved in its
  configuration, or else the first model Ollama lists, which could be a `-cloud` one; `OLLAMA_NO_CLOUD=1` on the
  server refuses those.
- **The host.** ollmcp doesn't read `OLLAMA_HOST`; it uses `--host`, else the host saved in
  `~/.config/ollmcp/config.json` (`providers.ollama.host`, written by `/save-config`), else
  `http://localhost:11434`. Passing `--host` as above overrides any saved value.
- **Update check.** At each start ollmcp asks pypi.org for its latest version number. The request carries none of
  your data, and 0.35.1 has no setting to turn it off.
- ollmcp has no telemetry in 0.35.1, and keeps its settings and logs under `~/.config/ollmcp/`.

**To confirm the model address is loopback** while a chat runs, list the client's connections:

```bash
ss -tnp | grep -i ollmcp                 # every peer should be 127.0.0.1:11434 (or [::1]:11434)
```

The `jobhunt` server itself has no network connection at all; it talks to the client over a pipe.

### Seeing what the model was sent

The client's screen shows what the model wrote, and jobhunt's spans (below) show the tool calls, but neither shows
the request the model actually received: the messages, tool descriptions, thinking setting and options the client
sent. `scripts/ollama_capture.py` (standard library only) records that. It sits between the client and Ollama,
passes every request and reply through unchanged, streamed replies included, and appends each exchange to a file as
one JSON line:

```bash
python scripts/ollama_capture.py --out /tmp/ollmcp-capture.jsonl \
    --listen 127.0.0.1:11436 --upstream http://127.0.0.1:11434
# in another terminal: the same ollmcp command, with only the host changed
ollmcp --provider ollama --host http://127.0.0.1:11436 --model qwen3:8b \
    --servers-json ~/.config/ollmcp/jobhunt-demo.json
```

Each line has the method, path, status and times, the request as sent (for `/api/chat`: `model`, `messages`,
`tools`, `think`, `options`) and the reply. A streamed reply keeps every chunk and puts them together under
`response.assembled`: the answer, the thinking, the tool calls, and Ollama's counts, such as `prompt_eval_count`
(the prompt's length in tokens, worth comparing with the model's context size). For example, to list each chat
request's length, its last message and what came back:

```bash
python3 -c '
import json, sys
for line in open(sys.argv[1]):
    r = json.loads(line)
    if r["path"] != "/api/chat": continue
    a, last = r["response"]["assembled"], r["request"]["messages"][-1]
    print(r["seq"], a.get("prompt_eval_count"), last["role"], repr(str(last.get("content"))[:60]),
          [c["function"]["name"] for c in a["tool_calls"]] or repr(a["content"][:60]))
' /tmp/ollmcp-capture.jsonl
```

Both addresses must be loopback ones, and the proxy refuses any other, so it can't become a way for requests to
leave the machine. The capture holds every tool result the model read, so treat it like the database: keep it out
of the repository (`data/` is ignored) and delete it when done.

## Connecting other clients

Any MCP client that starts a server from a command can use `jobhunt mcp`: give it the command (the venv's
`jobhunt`, by absolute path) and the arguments `mcp --db <absolute database URL> --share <scopes>`, as in the file
above, following that client's own documentation for where its configuration goes. **Remember that a client's model
receives whatever the named scopes share**: with a client backed by a cloud model, that includes your postings and
triage (`postings`) or your skill levels and match figures (`profile`). Start with the demo database, and share only
the scope you need.

The server speaks MCP over standard input and output only. A client that reaches servers over HTTP alone (including
through a proxy that puts an HTTP port in front of a stdio server) isn't supported: a listening port would need
authentication that the server doesn't have.

## Trying it on the demo

The demo database holds an invented person's job search; nothing in it is yours.

```bash
jobhunt demo                             # builds ./demo/jobhunt.db and ./demo/documents
```

Then use `sqlite:////path/to/jobhunt/demo/jobhunt.db` as the `--db` above.

### Checking with another client

jobhunt's tests talk to the server through the Python MCP SDK's own client. The
[MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a client written separately, in TypeScript, with
no model. Run it on the demo after upgrading the `mcp` package, and after adding a tool or changing a tool's arguments
or results, to see the tools as other clients see them. It needs Node.js, and `npx` downloads it from npm.

The Inspector's documentation doesn't say how a server's own flags are kept apart from its options, so start the
server through a one-line script:

```bash
cat > /tmp/jobhunt-demo-mcp.sh <<'EOF'
#!/bin/sh
exec /path/to/jobhunt/venv/bin/jobhunt mcp --share postings,profile --db sqlite:////path/to/jobhunt/demo/jobhunt.db
EOF
chmod +x /tmp/jobhunt-demo-mcp.sh

I="npx -y @modelcontextprotocol/inspector@2.13.0 --cli /tmp/jobhunt-demo-mcp.sh --format json"
$I --method tools/list --strict          # the tools and their schemas; exit 6: a schema other clients may not read
$I --method tools/call --tool-name get_posting --tool-arg job_id=1
$I --method tools/call --tool-name recommendations --tool-args-json '{"workplace":["Remote"]}'
$I --method tools/call --tool-name search_postings --tool-arg q=Engineer --tool-arg bogus=1   # runs, warns about bogus
$I --method tools/call --tool-name search_postings --tool-arg bogus=1   # nothing usable: refused, naming bogus
```

Every input schema should have `"additionalProperties": false`. Every call should return `"isError": false` with
`structuredContent`, except the refused one; the call with `bogus` beside `q` has `warnings` first. Change `--share` in the script to see each scope's tools on its own.

## Tracing tool calls

With a trace viewer on this machine ([docs/tracing.md](tracing.md)), add `--otlp-endpoint` to the server's
arguments, for example `"--otlp-endpoint", "http://localhost:4318/v1/traces"`. Each tool call is then one span with
the tool's name, the posting id it names, and counts and sizes, but no text; `--trace-content` adds the call's
arguments. A tool's result is never put in a span. See "Tool calls" in [docs/tracing.md](tracing.md#tool-calls).

## When the server refuses to start

Everything the command prints goes to standard error (standard output is the protocol), so look in the client's
log for these. Each exits with status 2 and changes nothing.

- **No `--share`, or an unknown scope:** name `postings`, `profile` or both.
- **No database file at the path:** the server never creates a database. Give `--db` the absolute path of an
  existing one.
- **The database is at an older schema version:** run `jobhunt import` or `jobhunt serve` once on it to upgrade
  it; the MCP server never migrates.
- **The `mcp` extra isn't installed:** `pip install -e ".[mcp]"` in jobhunt's venv.
