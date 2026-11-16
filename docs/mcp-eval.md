# Measuring how a model uses the MCP server

`scripts/mcp_eval/` measures how a model answers questions with jobhunt's MCP tools ([docs/mcp.md](mcp.md)), so a
change to the tools' wording or results is adopted only when it measures better. It runs on the demo database only,
with the client and model that [docs/mcp.md](mcp.md#keeping-everything-on-this-machine) documents (ollmcp with
`qwen3:8b` on a local Ollama), and it runs a model only when you start it.

The scripts aren't part of the `jobhunt` package. Run them with the project venv's Python. They need the `mcp`
extra, and they write to the ignored folder `data/mcp-eval/`.

## Why

`add-mcp-server` adopted its wording from batches of whole client sessions: about 12 minutes for 3 sessions of five
questions, so 3 to 6 samples a wording. At that size a stage moved by one or two questions with nothing changed, and
every wording was tuned on one question (the design's D9, `openspec/changes/archive/*-add-mcp-server/design.md`).
Here, each question is sampled many times on its own (a *rollout*), a held-out set is kept that the wording is never
tuned on, and two code versions are compared by an exact test.

## Setting up

1. **Ollama, local, with an 8192-token context.** As in [docs/mcp.md](mcp.md#1-keep-ollama-local):
   `OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=8192 ollama serve` (or the same two variables in the systemd unit), and
   `ollama pull qwen3:8b`. The client sends no context size, so the server's own is used; the scripts stop after the
   first request when the loaded model's context is below 8192 (`/api/ps`).
2. **The demo.** The default database is `data/mcp-eval/demo/jobhunt.db`, built with `jobhunt demo` the first time
   a command needs it. Any other database must have been built by `jobhunt demo`. Every command opens its database
   read-only and refuses one that `jobhunt demo` didn't build (exit 2), so it can't run on your data.
3. **The client, for session batches only.** ollmcp 0.35.1 in its own venv:

   ```bash
   python3 -m venv data/mcp-eval/ollmcp-venv && data/mcp-eval/ollmcp-venv/bin/pip install ollmcp==0.35.1
   ```

Every Ollama address must be an `http://` loopback address (`localhost`, `127.0.0.0/8`, `::1`), and environment
proxies are ignored. Every command first states what it will send. Use `--dry-run` to stop there.

## Commands

```bash
# Rollouts: each question of a set sampled 10 times (the default) with the working tree's server
venv/bin/python scripts/mcp_eval/rollout.py baseline-dev --set dev
venv/bin/python scripts/mcp_eval/rollout.py baseline-dev --set dev --dry-run       # states it, sends nothing
venv/bin/python scripts/mcp_eval/rollout.py try-q --set dev --questions dev-2,dev-3 --samples 10
# Single-step rollouts: only each question's first request (30 samples by default), for first-call decisions
venv/bin/python scripts/mcp_eval/rollout.py first-dev --set dev --first-step
# Continue a stopped rollout stage (Ctrl-C, a failed request, a reboot) with its own options
venv/bin/python scripts/mcp_eval/rollout.py baseline-dev --resume

# Report a stage, or several
venv/bin/python scripts/mcp_eval/score.py data/mcp-eval/stages/baseline-dev
# Compare the current code's stage with a candidate's
venv/bin/python scripts/mcp_eval/compare.py data/mcp-eval/stages/baseline-dev data/mcp-eval/stages/candidate-dev
# One dev question's calls, results and answer, per sample (with --thinking, the model's thinking too)
venv/bin/python scripts/mcp_eval/detail.py data/mcp-eval/stages/baseline-dev dev-2 --sample 3

# Session batches through the real client: 3 fresh ollmcp sessions of the dev set, each through a capture proxy
venv/bin/python scripts/mcp_eval/batch.py confirm-dev --runs 3 --set dev
# The fidelity check: a session's capture against the requests a rollout builds
venv/bin/python scripts/mcp_eval/rollout.py --check data/mcp-eval/stages/confirm-dev/run1/capture.jsonl
```

Common options: `--model` (default `qwen3:8b`), `--ollama-url` (default `http://127.0.0.1:11434`), `--db` (the demo).
Each stage is a new folder `data/mcp-eval/stages/<name>/`, and a name already used is refused. Its `stage.json`
holds what ran: kind, set, questions, model, samples, Ollama version, git commit, a hash of `mcp_server.py` and
`mcp_tools.py`, the tools as sent, and the demo's company names. `code/` holds copies of those two files. A rollout
stage writes `samples.jsonl` (every request, reply and tool result; requests leave out the tools, which are in
`stage.json`), and a session stage writes `run<k>/` (the proxy's `capture.jsonl`, the terminal record
`session.raw`, the connections `session.conns.json`, `driver.out`).

A rollout stage writes each sample as it finishes, so stopping one keeps what it recorded. `--resume` runs only
the samples it lacks, with the stage's own set, questions, samples, model and kind (giving any of those is refused).
It's refused when `mcp_server.py` or `mcp_tools.py` changed, when the set's questions or history answers changed,
when the tools as sent differ, or when Ollama's version differs, since any of these would mix two runs in one stage.
`score.py` and `compare.py` say when a stage is unfinished. Session batches don't resume.

Sessions and rollouts run the working tree's code, so don't edit `src/` while one runs. To measure a candidate,
make the change, run its stages, and compare them with the current code's.

## What a rollout sends

A rollout sends Ollama the requests ollmcp 0.35.1 sends, without the client. This was read from its source and
checked against captures:

- **Tools:** each tool the server lists, in its order, as `{"type": "function", "function": {"name":
  "jobhunt_<tool>", "description": "[jobhunt] <description>", "parameters": ...}}`. The parameters pass through the
  `ollama` package's `Tool` model, which keeps only the schema's `type`, `$defs`, `items` and `required`, and each
  property's `type`, `items`, `description` and `enum`. **Titles, defaults, `minimum`/`maximum`,
  `additionalProperties` and a nullable property's `anyOf` never reach the model.** For example, `search_postings`'
  `workplace`, `status` and `min_interest` arrive with their descriptions only, and no type or allowed values.
- **Request:** `{model, stream, options: {}, think: "medium", messages, tools}`. Rollouts send `stream: false`,
  which doesn't change sampling.
- **History:** each earlier question of the set as a `user` message with its written `history_answer` as an
  `assistant` message, then the question. (ollmcp keeps each earlier question with its final answer, and leaves out
  a question stopped at the loop limit.)
- **Within a question:** each reply as `{"role": "assistant", "content": ..., "tool_calls": [{"function": {"name",
  "arguments"}}]}`, with the content left out when it's empty. Then one `{"role": "tool", "content": ...,
  "tool_name": ...}` per call. Its content is the result's text blocks joined by a blank line, the same for an error
  result (`Error executing tool ...`). A call to a name the client doesn't offer gets no tool message. After 7
  rounds of calls the client asks the user, and the rollout records the question as unanswered.

Each tool call is answered by the working tree's server in-process, through the SDK's in-memory client, so the
arguments are sifted as in a session. Results are always the current code's.

**The fidelity check** (`rollout.py --check CAPTURE`) rebuilds each request of a real session's capture, using the
capture's own questions, answers and tool calls, with results from the working tree's server. It then compares the
tools, options and messages, and exits 1 when a request differs. Run it on a fresh session of the same code
whenever the documented ollmcp version changes, and record the result here:

| ollmcp | Checked | Result |
|---|---|---|
| 0.35.1 | 2026-11-15, the six `add-mcp-server` sessions of its last wording (`q-substring`, `q-substring-b`) and `tests/fixtures/mcp_eval/session-capture.jsonl` | every request equal (12 or 14 a session) |
| 0.35.1 | 2026-11-15, a fresh dev-set session on this change's code (ollama 0.6.3, Ollama 0.32.1, `qwen3:8b`) | 13 of 13 requests equal |

## Question sets

`scripts/mcp_eval/questions/dev.json` and `holdout.json` hold five questions each, asked in order: each question's
history is the questions before it in its set. Each question has:

- `id`, `text`, and `history_answer` (a short right answer written by hand, used as history for later questions, so
  every stage has the same history and none comes from a transcript);
- `checks`, from this vocabulary:
  - `answer_urls`: the posting URL numbers the answer must hold, `exact` or `includes`;
  - `answer_figures`: values the answer must report, up to rounding (within 0.01, as a decimal or a percent);
  - `answer_mentions`: names the answer must hold (ignoring case and curly apostrophes);
  - `answer_amounts`: the money amounts the answer must state, and the only ones it may state;
  - `called`: a tool call the sample must make, with at least these arguments;
  - `first_call`: the question's first call, with its tool, its `arguments` (values), arguments it must have (`with`)
    and arguments it must not have (`without`);
- `unasked_filters`: search filters the question doesn't ask for, for the carried-filter diagnostic;
- `sources`: the tool calls whose results hold the expected facts. `tests/test_mcp_eval.py` builds the demo and
  checks every expected URL, figure, mention, amount and call against them, so a demo change that moves a fact fails
  the suite, naming the question and the fact.

**Dev** is the five questions `add-mcp-server` was tuned on. **Held-out** has five questions drafted before any run:
a filter other than `workplace` left by an earlier question (`tag`), a dismissed posting asked about by name, a
question naming only a company, and a posting named by the number in its URL.

### Held-out questions

Held-out questions are never tuned on. `score.py` and `compare.py` show them as pass and diagnostic counts only,
which is all they ever print. `detail.py` refuses a held-out question and shows nothing of it. With `--reveal`, it
shows the question and moves it from `holdout.json` to the end of `dev.json` with its id kept, so git shows the move,
and says so. A question whose transcript was read can be tuned on, so the move is permanent, and nothing moves from
dev to held-out. Moving a question changes the held-out set's history, so held-out stages from before a move don't
compare with later ones. The records under `data/mcp-eval/` hold everything and can be opened by hand. Don't open
held-out ones, and don't let an agent read them: the rule is procedural, like the skill eval's holdout set.

## The report

`score.py` reports each question's samples that passed, each scored check's passes, and how many samples showed
each diagnostic. It also reports the number of samples in which every question passed (session runs, or rollouts
paired by sample number). A sample passes a question when every check scored passes. **A full stage** (sessions,
rollouts) scores every check except `first_call`, and **a single-step stage** scores only `first_call`, since it has
no answer. The report says which. A single-step stage is evidence for a first-call decision, not for a question's
answer.

Diagnostics, counted in every sample:

| Diagnostic | Seen when |
|---|---|
| `url_as_job_id` | a `job_id` above 10⁹ (the number in a posting's URL) is passed |
| `combined_q` | a search `q` holds a demo company's name and other words |
| `invented_args` | a call has an argument the tool's schema doesn't have |
| `unknown_tool` | a call names a tool the client doesn't offer |
| `carried_filter` | a search uses one of the question's `unasked_filters` |
| `made_up_amount` | the answer states a money amount that none of the sample's tool results holds |
| `refused` | a result is an error (a refused call, or a posting not found) |
| `warnings` | a result begins with `warnings` (arguments left out) |
| `unanswered` | the question stopped at the loop limit (full stages only) |

The report also gives the mean number of tool calls a sample and the largest prompt in tokens.

## The verdict, and adopting a change

`compare.py CURRENT CANDIDATE` gives each question both pass counts and a verdict. The verdict comes from a
one-sided exact test (Fisher's) of the two counts at p ≤ 0.05: `better` when the candidate passes more often,
`worse` when it passes less often, `within noise` otherwise. Both p-values are shown. The set is `better` when some
question is `better` and none is `worse`, `worse` when any question is `worse`, and `within noise` otherwise. Stages
of different sets, kinds or models are refused. Equal code hashes, different Ollama versions and different sample
counts are warned about. With `--questions`, only the questions in both stages are compared, and the report names
the rest.

At 10 samples against 10, 2 against 8 passes gives p ≈ 0.012 (`better`), and 6 against 8 gives p ≈ 0.31 (`within
noise`). Large effects are found, and differences of one or two samples aren't claimed. No correction is made for
testing five questions at once, so the rule asks for more than one `better`:

**A change to the server's tool descriptions, argument descriptions, instructions or result fields, made to change
how models use the tools, is adopted only when all of the following hold, with the same model:**

1. full rollouts against the current code give the dev set `better`, with no dev question `worse`;
2. the held-out set isn't `worse`;
3. a session batch with the change (`batch.py`) shows no question that the rollouts passed failing in every
   session.

The change's design records the comparison's figures (held-out as counts). A candidate that isn't adopted is removed
from the code.

## Costs

Every measurement runs a model on your GPU and is started by hand. Nothing schedules or repeats one.

Measured on 2026-11-16 (`qwen3:8b` wholly in VRAM on a 16 GB GPU, an 8192 context, Ollama 0.32.1; the design of
`add-mcp-eval`, "Baselines"):

| Stage | Samples | Time | A sample |
|---|---|---|---|
| full rollouts, dev set | 10 a question, 50 | 39 min | 47 s (12 s for dev-4, 40–65 s for the others) |
| full rollouts, held-out set | 10 a question, 50 | 28 min | 34 s |
| single step, dev set | 30 a question, 150 | 60 min | 24 s |

A single step is about half a full rollout, most of it the model's thinking. So a single-step stage of the whole set
costs more than a full one. Measure a first-call decision on the questions it concerns, for example
`--first-step --questions dev-2` (30 samples, about 12 minutes). Comparing a candidate with the current code by the
adoption rule needs a full dev stage and a full held-out stage of the candidate, about 70 minutes, plus a session
batch. Two full dev stages of the same code compared as `within noise` on every question.
