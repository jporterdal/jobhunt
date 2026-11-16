## Why

`add-mcp-server` adopted its tool wording from batches of whole client sessions: about 12 minutes for 3 runs of five questions, so each wording had 3 to 6 samples. At that size a stage moved by one or two questions with nothing changed, only jumps like 0 against 3 runs could be read, and every wording was tuned on one question (the Machine Learning Engineer posting), with nothing to show whether a sentence that fixes it holds for questions it wasn't written for. The harness that made those runs lives in ignored `data/mcp-smoke/`, with no tests, and its expected answers are written into its code. Before any more wording or result changes (a statement about the leftover `workplace` filter, naming the postings a filter hid), the project needs a way to measure them that is fast enough for real sample sizes, keeps a held-out set it never tunes on, and says when a change counts as better.

## What Changes

- **`scripts/mcp_eval/`** (new, tracked, outside the package, demo data only): the session harness moved out of `data/mcp-smoke/harness/` (driving ollmcp in a pseudo-terminal through `scripts/ollama_capture.py`, one session per run), rewritten so its expected answers come from the question sets rather than its code.
- **Rollouts** (new): a small client loop that sends Ollama the requests ollmcp would send (its tool rendering, its history of earlier questions and final answers, its loop limit), answers each tool call in-process with the working tree's server, and samples one question many times from a fixed history. No terminal, no confirmations, and the tool descriptions and results are always the current code's. A single-step mode samples only the first tool call of a question, for decisions such as "does the search keep `workplace`".
- **Fidelity check**: the rollout loop's requests are checked against a real ollmcp capture for the same history, so a rollout measures what the client would have sent.
- **Question sets**: a **dev** set (the five questions used so far) and a **held-out** set of new questions on the demo that exercise other cases (a filter carried from an earlier question other than `workplace`, a dismissed posting asked about by name, a company-only question, a posting named by the number in its URL). Each question carries its expected facts and checks in a data file. Held-out results are reported as figures only; reading a held-out question's transcripts moves it to dev, never the other way.
- **Report and verdict**: per question and set, how often each check passed and the diagnostics seen so far (URL number as `job_id`, title and company in one `q`, invented arguments, a filter kept from an earlier question, made-up figures), and a comparison of two code versions per question, `better`, `worse` or `within noise`, by a one-sided exact test at p ≤ 0.05.
- **Adoption rule**: a wording or result change to the MCP server is adopted only when the dev set's verdict is `better`, no dev question is `worse`, and the held-out set isn't `worse`; confirmed with one session batch through the real client.
- **Safety**: every command refuses a database that isn't a demo database, talks only to loopback addresses, and runs no model unless started by hand.
- `docs/mcp-eval.md`, CLAUDE.md and tests for the scripts. `data/mcp-smoke/` stays as the record of the earlier runs; new runs go to `data/mcp-eval/`.

## Capabilities

### New Capabilities

- `mcp-evaluation`: measuring how a model uses the MCP server's tools on the demo database: the question sets and their checks, sessions through the documented client, rollouts that reproduce the client's requests, the report, the comparison verdict and the rule for adopting a wording or result change.

### Modified Capabilities

None. The MCP server's behaviour doesn't change; later wording changes are measured with this one.

## Impact

- **New:** `scripts/mcp_eval/` (session driver, batch runner, rollouts, scorer, detail viewer, comparison), `scripts/mcp_eval/questions/dev.json` and `holdout.json`, `docs/mcp-eval.md`, `tests/test_mcp_eval.py` (no Ollama: a stub for chat, the in-memory server for tools).
- **Uses:** `jobhunt.mcp_server` and `jobhunt.mcp_tools` in-process (the `mcp` extra), `scripts/ollama_capture.py`, and the demo database (`jobhunt demo`). No change to `src/jobhunt/`.
- **Outside the repository:** ollmcp 0.35.1 in an ignored venv under `data/mcp-eval/` for sessions; a local Ollama for both modes. Runs, captures and rollouts stay under ignored `data/mcp-eval/`.
- **GPU:** every measurement runs a model on the user's GPU and is started by the user (or with their permission).
- **CI:** the new tests run with the existing extras; no model.

## Parser impact

None: see [parser-impact.md](parser-impact.md).
