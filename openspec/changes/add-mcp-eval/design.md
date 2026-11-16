## Context

See proposal.md for why. What exists:

- **The harness** in ignored `data/mcp-smoke/harness/`: `drive.py` drives ollmcp in a pseudo-terminal (types each question, answers each tool confirmation `y`, aborts at the loop limit, records the process tree's TCP connections); `batch.sh` runs N sessions, each through its own `scripts/ollama_capture.py` proxy (`127.0.0.1:11436` → `11434`); `score.py` scores captures with the expected answers written into its code (URLs, `0.644375`, `$105,000–$125,000`); `detail.py` prints a question's calls, results, answer and thinking; `replay.py` re-renders a terminal log with `pyte`. Runs, captures, code snapshots and the demo database it used sit beside it, with ollmcp 0.35.1 in its own venv.
- **What ollmcp 0.35.1 sends** (read from its source and confirmed by captures, `add-mcp-server` D9): through litellm to Ollama's `/api/chat`, `{model, stream: true, options: {}, think: "medium", messages, tools}`. Each tool is `{"type": "function", "function": {"name": "jobhunt_<tool>", "description": "[jobhunt] <description>", "parameters": <input schema>}}`. A new question's messages are the earlier questions and their final answers, then the question; within it, each assistant reply with its `tool_calls` and one `tool` message per call, whose content is the result's text blocks joined by a blank line (the structured content only when there's no text). Tool loops stop after 7 (`loop_limit`), when the client asks what to do.
- **The demo** is deterministic (`demo-data`: same rows, ids and texts on every build) and marked by the `demo.created_at` setting. `jobhunt mcp` and `db.read_only_engine` already open a database read-only.
- **The measured state** (`add-mcp-server` D9): 3–6 samples a stage, one question (Q2) carrying every decision, and a noise level of one or two questions per stage.

## Goals / Non-Goals

**Goals:**
- Enough samples per question to separate a real effect from noise, at a cost of minutes per decision rather than hours.
- Measures that stay valid when the tools' wording or results change: requests built from the working tree, not replayed text.
- A held-out set the wording is never tuned on, and a stated rule for adoption.

**Non-Goals:**
- Measuring other clients or providers. The documented client (ollmcp with a local Ollama) is the only one; another would be its own rendering and fidelity check.
- Measuring models for their own sake, or choosing the documented model. Comparisons hold the model fixed.
- Running in CI. Tests check the scripts without a model; measurements run on the user's GPU.
- Changing the MCP server. Wording and result changes come in later changes, measured with this one.

## Decisions

### D1. Scripts beside the package, not in it

`scripts/mcp_eval/` holds the commands, run as `venv/bin/python scripts/mcp_eval/<command>.py` (as `scripts/ollama_capture.py` is). They drive an outside client and model on the demo, never the user's data, so they don't belong to `jobhunt`'s commands, and `jobhunt eval` (skill extraction and linking, on the user's labels) stays separate. They may import `jobhunt` (the venv has it editable) and need the `mcp` extra; nothing in `src/jobhunt/` imports them.

| File | Holds |
|---|---|
| `common.py` | the demo guard and read-only engine, the loopback check, the data folder layout, reading question sets, the ollmcp rendering of tools and results (D3) |
| `session.py` | one ollmcp session in a pseudo-terminal (today's `drive.py`, unchanged in behaviour) |
| `batch.py` | N sessions, each through its own capture proxy (today's `batch.sh`, in Python so it can share the guard and be tested) |
| `rollout.py` | rollouts and single-step rollouts (D3, D4) |
| `score.py` | turns a session capture or a rollout record into per-question records (calls, results, answer), applies the checks and diagnostics (D5), prints a stage's report |
| `compare.py` | the verdict between two stages (D7) |
| `detail.py` | one sample's calls, results, answer and thinking; refuses held-out questions without `--reveal` (D6) |
| `questions/dev.json`, `questions/holdout.json` | the question sets (D5, D6) |

`replay.py` (pyte) is dropped: every new run has a capture. Outputs go to ignored `data/mcp-eval/`: `demo/` (built with `jobhunt demo` when missing), `ollmcp-venv/` (made by hand, as `docs/mcp-eval.md` says, `mcp-client-for-ollama==0.35.1`), and `stages/<stage>/` with `stage.json` (what ran: kind, set, model, counts, Ollama version, the git commit and a hash and copy of `mcp_server.py` and `mcp_tools.py` from the working tree) and one record per sample. `data/mcp-smoke/` stays as the record of `add-mcp-server`'s runs and isn't re-scored.

*Alternative considered:* a `jobhunt eval --mcp` command. It would put an outside client, a pseudo-terminal driver and a model loop into the package for a development-only task, and suggest it can run on the user's database.

### D2. Guards

- **Demo only.** Every command opens its database with `db.read_only_engine` and refuses one without the `demo.created_at` setting (exit 2, before any request or client), so it can't run on the user's data and can't write to the demo. Sessions pass the same database to `jobhunt mcp`.
- **Loopback only.** The Ollama address must be loopback (`localhost`, `127.0.0.0/8`, `::1`), checked the way `ollama_capture.py` checks its addresses; otherwise exit 2.
- **Stated first.** Each command prints, before any request, the questions, samples per question and code version, and whether it runs sessions or rollouts; `--dry-run` stops there. Nothing runs on a schedule.
- **Context size.** ollmcp sends no options, so the context is the server's. A rollout or batch reads `/api/ps` after the first request and stops with a message when the loaded model's context is below 8192 (question 5 overflowed 4096), rather than sending `num_ctx`, which the client doesn't.

### D3. Rollouts: the client's requests without the client

A rollout of question *k* of a set:

1. **History**: for each earlier question, a `user` message with its text and an `assistant` message with its recorded answer (D5), as ollmcp keeps them; then the question as a `user` message.
2. **Tools**: listed from `mcp_server.build(engine, ("postings", "profile"))` through the SDK's in-memory client, then rendered as ollmcp renders them (`jobhunt_` name prefix, `[jobhunt] ` description prefix, the input schema as `parameters`), in the order ollmcp lists them.
3. **Request**: `{model, stream: false, options: {}, think: "medium", messages, tools}` to `/api/chat`. Only `stream` differs from the client: it doesn't change sampling, and a single reply is simpler to record.
4. **Loop**: the reply is appended as ollmcp appends it (`assistant`, its content and `tool_calls`); each tool call is answered by calling the tool on the same in-memory client (so `_sift`, warnings and refusals apply), rendered as ollmcp renders results (text blocks joined by a blank line; ollmcp's own text for an error result and for an unknown tool), and appended as a `tool` message; repeat until a reply has no tool calls (the answer) or 7 loops have run (unanswered).
5. **Record**: every request, reply and tool result, with the stage and question.

Tool names arrive prefixed (`jobhunt_search_postings`); a name without the prefix or not listed is answered as ollmcp answers an unknown tool.

**Fidelity** (spec "Rollouts match a real capture"): `rollout.py --check CAPTURE` takes a real session's capture of the same code and, for each of its requests, builds the rollout's request from the same history and the capture's own tool calls and results, and compares tools, options and messages. Rendering details the source reading may have missed (how litellm writes an assistant message's `tool_calls`, whether arguments are objects or JSON text, error wording) are fixed against this check when implementing, from a fresh demo session. It's run again whenever the documented ollmcp version changes; `docs/mcp-eval.md` records the version it last passed with.

*Alternative considered:* replaying captured requests with only the tools swapped. That freezes earlier tool results at the old code's, so a result change (such as naming what a filter hid) couldn't be measured, and each replay would depend on one session's history.

### D4. Single-step rollouts

`rollout.py --first-step` sends only a question's first request and records its tool calls: seconds a sample instead of a minute, for decisions made in the first call (does the first search keep `workplace`, combine title and company, or use the URL number as a `job_id`). Checks marked `first_call` (D5) are scored on them; checks on the answer aren't, and the report says which checks a stage scored. A single-step stage is evidence for a decision, not for a question's answer; the adoption rule (spec) uses full rollouts.

### D5. Question sets

One JSON file per set: an ordered list of questions, each with:

- `id` (`dev-2`, `holdout-3`), `text`;
- `history_answer`: the final answer used as history for later questions. It is written by hand as a short right answer (the facts, with links), not taken from a model's run, so that held-out history needs no transcript read and every stage uses the same history;
- `checks`: a list from a small vocabulary, each scored on a sample:
  - `answer_urls` (`exact` or `includes`: posting URL numbers),
  - `answer_figures` (values, matched up to rounding: within 0.01, as a decimal or a percent, as today),
  - `answer_mentions` (names, case-insensitive),
  - `answer_amounts` (the only money amounts allowed; any other fails),
  - `called` (a tool with a subset of arguments, e.g. `posting_fit` with `job_id` 3),
  - `first_call` (the first call's tool, required arguments and arguments it must not have);
- `unasked_filters`: filter arguments the question doesn't ask for, for the carried-filter diagnostic.

**Diagnostics**, computed for every sample whatever its question: URL number as `job_id` (an integer above 10⁹), a title and a company in one `q` (a `q` holding a demo company name and other words), invented arguments (names outside the tool's schema), a carried filter (an argument in `unasked_filters` on any search), a made-up amount (a money amount in the answer that no tool result of that sample holds), refused calls, results with warnings, tool calls, the largest prompt in tokens.

**Expected facts are tested** (`tests/test_mcp_eval.py`): the demo is built and each check's URLs, figures, mentions, amounts and called arguments are compared with what the tools return for the posting the question names, so a demo change that moves a fact fails the suite. The test lives with the other tests, uses only the demo and needs no model.

### D6. The sets, and keeping held-out held out

**Dev** is the five questions of `add-mcp-server` (remote postings; the Machine Learning Engineer posting's requirements and pay; the fit for Senior Data Analyst; expert skills; the best remote fits), already read and tuned on.

**Held-out** is new, drafted here before any run so no transcript has shaped it, and asked in this order so earlier questions leave filters behind:

1. Which of my shortlisted postings should I look at first? List each with its company and link. (the `shortlist` tag: jobs 1 and 5)
2. What does the Data Scientist, Credit Risk posting at Example Bank ask for? Include its link. (not shortlisted: a carried `tag` hides it)
3. What did the Instructor, Data Analytics posting at Example Polytechnic pay? Include its link. (dismissed: found only with `dismissed` `included`; $68,000–$74,000)
4. Which of my saved postings are at Example Labs? Link each one. (a company only: jobs 1 and 10)
5. How well do I fit posting 9000000108? Include its link. (the URL number: search for it, then `posting_fit` on job 8)

Their checks are filled in when implementing, from the tools' results on the demo, and the test of D5 holds them.

**Discipline:** `score.py` and `compare.py` print held-out questions as counts only. `detail.py` refuses a held-out question unless given `--reveal`; with it, it shows the sample and moves the question from `holdout.json` to `dev.json` (keeping its id, so git shows the move), and says so. Nothing moves from dev to held-out. The records under `data/` hold everything and can be read by hand; the rule is procedural, as the skill eval's holdout set is, and the `--reveal` move keeps it honest when a transcript is needed.

### D7. Verdict

For one question, stages A (current) and B (candidate) give pass counts *a* of *n* and *b* of *m*. The one-sided exact test (Fisher's, from the hypergeometric distribution with `math.comb`; no new dependency) gives p for "B passes more often" and for "B passes less often"; `better` or `worse` at p ≤ 0.05, else `within noise`. The set's verdict is `better` when some question is `better` and none `worse`, `worse` when any is `worse`. The comparison refuses stages of different sets, models or kinds, and warns when both stages' code hashes are equal.

Defaults: **10 full rollouts** a question per stage, **30 single-step** samples. At 10 against 10, 2 against 8 passes gives p ≈ 0.012 and 6 against 8 gives p ≈ 0.31: large effects, the kind seen so far, are found; one- or two-sample differences aren't claimed. The cost per sample is measured when implementing and recorded in `docs/mcp-eval.md`, with the defaults adjusted there if 10 proves too slow or too few.

There's no correction for testing five questions at once: a false `better` on one dev question is possible, which is why the held-out set must not be `worse` and a session batch must agree before adoption (spec).

*Alternatives considered:* the link eval's paired sign test, which needs paired items (here samples aren't paired); and pooling all questions into one count, which lets an easy question hide a hard one.

### D8. Sessions stay, as the confirmation

`session.py` and `batch.py` keep today's behaviour (the page's ollmcp command line, through a capture proxy, answering `y`, aborting at the loop limit, recording connections), store into `data/mcp-eval/stages/<stage>/run<k>/`, and are scored by the same `score.py` as rollouts. They are the slow, real measure: a batch confirms a candidate before adoption (spec "Adopting …") and a fresh one feeds the fidelity check (D3).

### D9. Tests

`tests/test_mcp_eval.py` loads the scripts by path (as `tests/test_ollama_capture.py` does) and needs the `mcp` extra (skipped without it): the guards (a non-demo database and a remote address refused before anything is sent; the dry run sends nothing); the rollout loop against a stub Ollama on loopback that answers scripted tool calls, checking the requests' tools, history and tool messages and that results come from the working tree's server on a built demo; the loop limit; the ollmcp rendering against a small capture fixture made from the demo (fictional data); every check and diagnostic on hand-made records; the verdict's p-values against known values; the held-out refusal and the `--reveal` move on a copy of the set files; and the expected facts against the demo (D5). No test calls a model.

### D10. Docs

`docs/mcp-eval.md`: what is measured and why (with a pointer to `add-mcp-server` D9), setting up (Ollama with an 8192 context, the ollmcp venv, the demo), the commands with examples, the question sets and their rules, the adoption rule, the costs measured, and the fidelity check's last passing ollmcp version. CLAUDE.md: `scripts/mcp_eval/` in the architecture, the commands, and a line in the MCP section that wording and result changes are adopted by this rule; the comment on `_ONE_PHRASE` points to it.

## Risks / Trade-offs

- **The rollout drifts from the client** (an ollmcp release changes rendering or history). → The fidelity check against a fresh capture; the documented version is pinned; sessions confirm before adoption.
- **Fixed history isn't the model's own.** In a session, question 2 follows the model's own answer to question 1; in a rollout, a hand-written one. → Effects that depend on the model's earlier wording show up in the confirming session batch; the history answers are short and factual so they carry the same facts (such as "remote") a model's answer would.
- **Held-out leakage.** Records under `data/` can be opened by hand, and an agent reading them would tune on them. → `detail.py`'s refusal and the `--reveal` move, the rule in the docs and CLAUDE.md, and git history of the set files.
- **Five questions, no correction.** → Held-out and session confirmation (D7).
- **Ollama's sampling defaults change between versions.** → Each stage records the Ollama version; the comparison warns when two stages differ.
- **GPU time.** 10 rollouts × 5 questions × 2 versions is roughly the length of one earlier batch per version, measured when implementing. → Single-step stages for first-call decisions; `--questions` to run a subset when only some questions are in play (the verdict then covers those only, and the report says so).

## Migration Plan

Nothing in the package changes. `data/mcp-smoke/` stays as it is; its figures are in `add-mcp-server`'s design. The first stages under the new scripts are the current code's dev and held-out baselines, which later changes compare against. Rollback is deleting `scripts/mcp_eval/`.

## Open Questions

- Whether a second model (`qwen3:14b`) should be part of the adoption rule. Left to a later change, once the cost per sample is known; the comparison already takes a model per stage.
