# Measuring how a model uses the MCP server

`scripts/mcp_eval/` measures how a model answers questions with jobhunt's MCP tools ([docs/mcp.md](mcp.md)), so you
can decide on evidence whether a change to the tools' wording or results is adopted. It runs on the demo database only,
with the client and model that [docs/mcp.md](mcp.md#keeping-everything-on-this-machine) documents (ollmcp with
`qwen3:8b` on a local Ollama), and it runs a model only when you start it.

The scripts aren't part of the `jobhunt` package. Run them with the project venv's Python. They need the `mcp`
extra, and they write to the ignored folder `data/mcp-eval/`.

## Why

`add-mcp-server` adopted its wording from batches of whole client sessions: about 12 minutes for 3 sessions of five
questions, so 3 to 6 samples a wording. At that size a stage moved by one or two questions with nothing changed, and
every wording was tuned on one question (the design's D9, `openspec/changes/archive/*-add-mcp-server/design.md`).
Here, each question is sampled many times on its own (a *rollout*), a held-out set is kept that the wording is never
tuned on, and two code versions are compared question by question, with each difference's size, precision and
strength of evidence.

## Terms

- **Question set:** `dev` or `held-out`, five questions in a fixed order, each with the checks its answer must pass
  ("Question sets" below).
- **History:** the messages a question is asked after. A stage asks its questions under one **history condition**:
  - `fixed` (the default): the earlier questions of the set, each with its hand-written `history_answer`;
  - `own`: the earlier questions of the same chain, each with the answer the model itself gave (a question stopped at
    the loop limit left out, as ollmcp leaves it out);
  - `none`: no earlier message; the question alone.
- **Rollout:** one simulated attempt at one question. It sends Ollama the requests ollmcp would send, without ollmcp,
  and answers each tool call with the working tree's server in-process, until the model answers or the loop limit.
  A **single-step rollout** sends only the question's first request and records the tool calls it asks for.
- **Chain:** rollouts of a whole set in order, each answer becoming history for the later questions (`own`). Chain
  *k* gives sample *k* of every question.
- **Session:** the real client (ollmcp) driven in a terminal through a capture proxy, asking the whole set in order.
  Its history is its own answers, so a session stage is `own`.
- **Sample:** one attempt at one question, scored pass or fail: a rollout, or one question's part of a chain or a
  session. "dev-2 passed 2/10" means 2 of dev-2's 10 samples passed every scored check.
- **Stage:** a batch of samples of one code version, set, model, kind (full, single-step or session) and history
  condition and order, in its own folder `data/mcp-eval/stages/<name>/`. Stages are what `score.py` reports and
  `compare.py` compares.
- **Order:** the order a stage asks the set's questions in, which decides a question's history under `fixed` and
  `own`: the set's order (the default) or `balanced` (below).

## History conditions and orders

Each condition answers a different question:

- **`fixed`** tells how a question does after the same, right history every time. Every sample has the same history,
  so samples are independent draws and two code versions compare cleanly. It is the default and the main condition
  for adoption.
- **`none`** tells how a question does on its own wording. A difference between `fixed` and `none` on the same code is
  the history's effect (for example, a `workplace` filter left by dev-1 carried into dev-2's search). Every question
  in a set must read on its own, so that it can be asked without history; a question that refers to an earlier one
  ("which of those pay the most?") isn't added.
- **`own`** tells what the model's own earlier answers (right or wrong) do to later questions, at rollout speed:
  closer to a session, but many more samples than a session batch. It's a diagnostic: it doesn't count toward
  adoption. `--questions` and `--first-step` are refused with it (a chain asks the whole set, and a first request
  needs the chain's earlier answers).

**The set's order is the default.** It keeps the carry-overs the sets were written for (holdout-1's `tag` before
holdout-2) in every sample. **`--order balanced`** is for one-off evaluations, such as "does dev-2 fail wherever it
sits, or only after dev-1?". It uses a Williams design: for *n* questions, the orders are built from `0, 1, n−1, 2,
n−2, …`, each next order adding 1 to every position, with every order reversed as well when *n* is odd. For five
questions that's ten orders, in which each question is asked twice in each position and twice directly after each
other question. Sample *k* uses order ((*k* − 1) mod 10) + 1, so the default 10 samples are exactly the ten orders
and cost nothing extra. A sample count that isn't a multiple of the orders is stated before the stage runs (the
stage isn't balanced), and `score.py` flags an unfinished balanced stage. `stage.json` holds the orders and each
sample its order (`row`). `balanced` is refused with `none`, where the order changes nothing. A balanced stage
spreads each question over ten histories, so its counts vary more: it attributes, it doesn't decide adoption.

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
# History conditions (default fixed) and orders (default set)
venv/bin/python scripts/mcp_eval/rollout.py none-dev --set dev --history none
venv/bin/python scripts/mcp_eval/rollout.py own-dev --set dev --history own
venv/bin/python scripts/mcp_eval/rollout.py balanced-dev --set dev --order balanced --questions dev-2
# Continue a stopped rollout stage (Ctrl-C, a failed request, a reboot) with its own options
venv/bin/python scripts/mcp_eval/rollout.py baseline-dev --resume

# Report a stage, or several
venv/bin/python scripts/mcp_eval/score.py data/mcp-eval/stages/baseline-dev
# Compare the current code's stage with a candidate's
venv/bin/python scripts/mcp_eval/compare.py data/mcp-eval/stages/baseline-dev data/mcp-eval/stages/candidate-dev
# Compare two conditions of the same code: each question's history (or order) effect
venv/bin/python scripts/mcp_eval/compare.py --conditions data/mcp-eval/stages/baseline-dev data/mcp-eval/stages/none-dev
# One dev question's calls, results and answer, per sample (with --thinking, the model's thinking too)
venv/bin/python scripts/mcp_eval/detail.py data/mcp-eval/stages/baseline-dev dev-2 --sample 3

# Session batches through the real client: 3 fresh ollmcp sessions of the dev set, each through a capture proxy
venv/bin/python scripts/mcp_eval/batch.py confirm-dev --runs 3 --set dev
# The fidelity check: a session's capture against the requests a rollout builds
venv/bin/python scripts/mcp_eval/rollout.py --check data/mcp-eval/stages/confirm-dev/run1/capture.jsonl
```

Common options: `--model` (default `qwen3:8b`), `--ollama-url` (default `http://127.0.0.1:11434`), `--db` (the demo).
Each stage is a new folder `data/mcp-eval/stages/<name>/`, and a name already used is refused. Its `stage.json`
holds what ran: kind, set, questions, model, samples, history condition, order (and a balanced stage's orders),
Ollama version, git commit, a hash of `mcp_server.py` and
`mcp_tools.py`, the tools as sent, and the demo's company names. `code/` holds copies of those two files. A rollout
stage writes `samples.jsonl` (every request, reply and tool result; requests leave out the tools, which are in
`stage.json`), and a session stage writes `run<k>/` (the proxy's `capture.jsonl`, the terminal record
`session.raw`, the connections `session.conns.json`, `driver.out`).

A rollout stage writes each sample as it finishes, so stopping one keeps what it recorded. `--resume` runs only
the samples it lacks, with the stage's own set, questions, samples, model, kind, history condition and order
(giving any of those is refused). An `own` stage stopped part-way through a chain continues that chain at its first
unrecorded question, with the chain's recorded answers as history. Stages from before conditions existed have none in
`stage.json` and read as `fixed` in the set's order (sessions as `own`).
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
- **History:** as ollmcp keeps it, each earlier question as a `user` message and its final answer as an `assistant`
  message (left out when empty), then the question; a question stopped at the loop limit is left out. Which earlier
  questions and answers depends on the stage's condition: under `fixed` the questions before it in the stage's order
  with their written `history_answer`s, under `own` the chain's questions with the model's answers, under `none`
  nothing.
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

`scripts/mcp_eval/questions/dev.json` and `holdout.json` hold five questions each, in order: under `fixed` in the
set's order, each question's history is the questions before it in its set. Each question reads on its own, so it
can also be asked under `none`. Each question has:

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
- `unasked_filters`: search filters the question doesn't ask for, for the `carried_filter` (or, without history,
  `unasked_filter`) diagnostic;
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
compare with later ones. In an `own` chain of the held-out set, the model's held-out answers are history for later
held-out questions; `detail.py` refuses those questions just the same. The records under `data/mcp-eval/` hold everything and can be opened by hand. Don't open
held-out ones, and don't let an agent read them: the rule is procedural, like the skill eval's holdout set.

## The report

`score.py` names the stage's history condition and order, and reports each question's samples that passed, each
scored check's passes, and how many samples showed each diagnostic. It also reports the number of samples in which
every question passed (session runs, rollouts paired by sample number, or `own` rollouts paired by chain). A sample passes a question when every check scored passes. **A full stage** (sessions,
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
| `carried_filter` | a search uses one of the question's `unasked_filters`, in a stage with history |
| `unasked_filter` | the same, in a stage without history (`none`), where nothing earlier could have carried it |
| `made_up_amount` | the answer states a money amount that none of the sample's tool results holds |
| `refused` | a result is an error (a refused call, or a posting not found) |
| `warnings` | a result begins with `warnings` (arguments left out) |
| `unanswered` | the question stopped at the loop limit (full stages only) |

The report also gives the mean number of tool calls a sample and the largest prompt in tokens. `detail.py` heads
each sample with its condition, and for a balanced order or an `own` chain with the questions asked before it.

## Comparing code versions

`compare.py CURRENT CANDIDATE` gives each question:

- **both pass counts**, `2/10 -> 6/10`;
- **the direction**: `more` when the candidate passes more often, `fewer` when less often, `same` when equally often.
  It describes the counts and nothing more;
- **the difference** in pass rate (the candidate's minus the current code's) with a **95% interval** (Newcombe's
  hybrid score interval, built from the two stages' Wilson intervals). It stays within −1 and +1 and behaves at 0/10
  and 10/10. When both stages passed, or both failed, every sample of a question, the report says so instead of giving
  an interval: the data say nothing about a difference there;
- **the mid-p value** for the observed direction (below).

The last line counts the questions in each direction (`directions: 2 more, 0 fewer, 3 same`). Nothing is compared
with a threshold, and there is no verdict for a question or the set. Stages of different sets, kinds, models, history
conditions or orders are refused, and the report names the condition. Equal code hashes, different Ollama versions
and different sample counts are warned about. With `--questions`, only the questions in both stages are compared, and
the report names the rest. `--json` gives each question's `current` and `candidate` counts, `direction`, `difference`,
`interval` (`[low, high]`, or `null` with `all_same` `"passed"` or `"failed"`), `mid_p_more` and `mid_p_fewer` (four
places; the text rounds differences to two places and mid-p to three), and the set's `directions`.

### Reading the figures

**The mid-p value.** Suppose the candidate made no difference: then the passes of both stages together would be
shared between them at random. The mid-p value for `more` is the chance, under that supposition, of the candidate
getting more passes than it did, plus half the chance of exactly its count. A small value says the counts would be
unusual if nothing had changed; it isn't the chance that nothing changed, and it says nothing about how large the
change is (the difference and its interval do). The two directions' values add to 1, so `same` is 0.5. Mid-p is used
instead of Fisher's exact p-value because, with the total of passes fixed, the exact p-value counts the whole of the
observed outcome as evidence against change and is too large at these sizes: for 2/10 → 6/10, Fisher's p is 0.085 and
the mid-p 0.047.

**A cross-check.** With uniform priors on both pass rates, the posterior probability that the candidate's rate is
*not* higher is close to the mid-p: 0.040 for 2/10 → 6/10, 0.155 for 7/10 → 9/10 (mid-p 0.167). Reading the mid-p as
"about the chance the direction is wrong" is a fair rough guide here.

**Why the intervals are wide.** At 10 samples against 10, an interval is 0.6–0.75 wide:

| Counts | Difference [95% interval] | mid-p |
|---|---|---|
| 2/10 → 8/10 | +0.60 [+0.16, +0.80] | 0.006 |
| 6/10 → 8/10 | +0.20 [−0.19, +0.52] | 0.192 |

The first is a large change measured well enough to be sure of its direction; the second is consistent with anything
from a small loss to a large gain. Differences of one or two samples tell little, and two full dev stages of the same
code differ by about that much (see "Costs"). No figure is corrected for testing five questions at once: none is
compared with a threshold, so there is no error rate to control, but among five questions one small mid-p by chance
is unremarkable.

### Adopting a change

A change to the server's tool descriptions, argument descriptions, instructions or result fields, made to change how
models use the tools, is adopted only by **your decision**. Before it, the change is measured with the same model,
comparing full rollouts of the candidate with the current code's in the set's order under both `fixed` and `none`
(dev and held-out sets), and with a session batch through ollmcp (`batch.py`). Whoever runs the measurement, a person
or an agent, presents the figures and asks you; it never decides, infers or assumes adoption from any figure or rule,
and being asked to run the measurement isn't a decision to adopt. The figures presented cover at least:

1. the direction and size of the dev differences under each condition;
2. any dev question that passed fewer samples, and by how much;
3. the held-out set's directions under each condition (counts and the figures computed from them);
4. any question that the rollouts passed and that failed in every session.

Both conditions are measured because a fix for something the history causes (a carried `workplace` filter) can't
show without history, and a fix to how a question alone is read may be hidden by history; a gain under one condition
can be paid for under the other. `own` and balanced stages are diagnostics, not part of the figures. The change's
design records the figures, your decision and your reasons. A candidate that isn't adopted is removed from the code.

### Comparing conditions

`compare.py --conditions A B` compares two stages of the same code (equal code hashes), set, model and kind whose
history condition or order differ: for example the current code's `fixed` stage with its `none` stage. It gives the
same figures per question (`more` when B passes more often), and the direction counts. It attributes an effect to the
history (or order) and decides nothing. Stages of different code, sets, models or kinds, or of the same condition,
are refused. For example, `baseline-dev` against `none-dev`:

```
  dev-2  2/10 -> 6/10    more   +0.40 [-0.02, +0.67]  mid-p 0.047
  dev-5  7/10 -> 9/10    more   +0.20 [-0.16, +0.51]  mid-p 0.167
```

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
adoption rule needs a full dev stage and a full held-out stage of the candidate under each of `fixed` and `none`,
about 70 minutes each condition (about 140 minutes), plus a session batch. The current code's stages are reused while
its code hash is unchanged. Two full dev stages of the same code (`baseline-dev`, `baseline-dev-2`) differed by one
sample on two questions (6/10 → 7/10 and 7/10 → 6/10, mid-p 0.338 each) and not at all on the other three.
