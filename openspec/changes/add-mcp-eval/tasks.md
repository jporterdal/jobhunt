## 1. Common ground

- [ ] 1.1 Create `scripts/mcp_eval/common.py` (D1, D2): the data layout under `data/mcp-eval/`, opening the database with `db.read_only_engine` and refusing one without `demo.created_at`, the loopback check for the Ollama address, and reading a question set file; verify in `tests/test_mcp_eval.py` (scripts loaded by path, as `tests/test_ollama_capture.py` does; skipped without the `mcp` extra) that a database built without `jobhunt demo` and a remote Ollama address each exit 2 before anything is sent, and that a demo built by the test is accepted
- [ ] 1.2 Add the ollmcp rendering to `common.py` (D3): tools from `mcp_server.build` listed through the in-memory client and rendered as `jobhunt_<tool>` / `[jobhunt] <description>` / `parameters`, and tool results rendered as ollmcp passes them (text blocks joined by a blank line; its texts for an error result and an unknown tool), taken from ollmcp 0.35.1's source; verify against a small fixture capture of a demo session (fictional data only) that the rendered tools and tool messages equal the captured ones

## 2. Question sets

- [ ] 2.1 Write `scripts/mcp_eval/questions/dev.json` with the five dev questions of D6, each with `id`, `text`, a hand-written `history_answer`, `checks` (today's `score.py` expectations as `answer_urls`, `answer_figures`, `answer_mentions`, `answer_amounts`, `called`, and `first_call` where a first-call decision applies) and `unasked_filters`; verify by the expected-facts test of 2.3
- [ ] 2.2 Write `scripts/mcp_eval/questions/holdout.json` with the five held-out questions of D6 in that order, their checks filled in from the tools' results on the demo (job numbers, URLs, the Example Polytechnic posting's pay, posting 8's match score), without running a model on them; verify by the expected-facts test of 2.3 and that no question id is in both files
- [ ] 2.3 Add the expected-facts test (D5): build the demo, and for every question compare each check's URLs, figures, mentions, amounts and called arguments with what the tools return for the posting it names; verify it passes, and fails naming the question and fact when one expected figure is changed locally (then restore it)

## 3. Scoring

- [ ] 3.1 Create `scripts/mcp_eval/score.py` (D5): per-question records (calls, results, answer, largest prompt) from a session capture and from a rollout record, every check and every diagnostic of D5 and the spec's "Report", a sample passing a question only when all its checks pass, and the stage report (per question and set; held-out as counts only); verify with tests on hand-made records for each check and diagnostic (including a made-up amount and a carried filter), and that `data/mcp-smoke/runs/q-substring/` scores Q2 3 of 3 and `change2/` 0 of 5 as the earlier scorer did
- [ ] 3.2 Create `scripts/mcp_eval/compare.py` (D7): per-question one-sided exact tests with `math.comb`, the question and set verdicts, the p-values, refusal for different sets, models or kinds, and warnings for equal code hashes or different Ollama versions; verify the p-values of 2/10 against 8/10 (≈ 0.0115), 2/10 against 9/10 (≈ 0.0027) and 6/10 against 8/10 (≈ 0.314) and the verdicts of the spec's scenarios
- [ ] 3.3 Create `scripts/mcp_eval/detail.py` (D6): one sample's calls, results, answer and, with `--thinking`, thinking; refusal of a held-out question without `--reveal`; with it, the question moved from `holdout.json` to `dev.json` with a message; verify on copies of the set files that the refusal shows nothing of the sample and that the move keeps the id and never goes from dev to held-out

## 4. Rollouts

- [ ] 4.1 Create `scripts/mcp_eval/rollout.py` (D3): history of earlier questions and `history_answer`s, tools rendered from the working tree, requests `{model, stream: false, options: {}, think: "medium", messages, tools}`, each tool call answered in-process through the in-memory client and appended as ollmcp appends it, stop at an answer or after 7 loops, and every request, reply and result recorded under `data/mcp-eval/stages/<stage>/` with `stage.json` (kind, set, model, counts, Ollama version, git commit, code hash and copies of `mcp_server.py` and `mcp_tools.py`); verify against a stub Ollama on loopback scripted to call `search_postings` then answer: the second request holds the working tree's result for those arguments on the demo, the tools carry a description changed in a test, and a stub that never answers is stopped after 7 loops and recorded as unanswered
- [ ] 4.2 Add `--first-step` (D4), `--questions`, `--samples` (defaults 10 full, 30 single-step), the statement of what will run and `--dry-run` (D2); verify the dry run sends no request, and a single-step stage records only first calls and is scored on `first_call` checks only
- [ ] 4.3 Add the context check (D2): after the first request, read `/api/ps` and stop with a message when the model's context is below 8192; verify against the stub reporting 4096 and 8192
- [ ] 4.4 Add `rollout.py --check CAPTURE` (spec "Rollouts match a real capture"): rebuild each captured request from the capture's history, calls and results and compare tools, options and messages; verify on the fixture capture of 1.2 that it reports equal, and a changed description reports the difference

## 5. Sessions

- [ ] 5.1 Move `drive.py` to `scripts/mcp_eval/session.py` and `batch.sh` to `scripts/mcp_eval/batch.py` (D8): same behaviour (the page's ollmcp command line, a capture proxy per session, `y` to each confirmation, abort at the loop limit, connections recorded), the guards of D2, output under `data/mcp-eval/stages/<stage>/run<k>/` with `stage.json`; verify with a test that runs `batch.py --dry-run` on the demo and checks what it states, and that a non-demo database is refused before a proxy or client starts

## 6. Measuring for real (on the user's GPU, only with their agreement)

- [ ] 6.1 With the user's agreement: start Ollama as `docs/mcp-eval.md` says, run one session of the dev set on the current code, and run `rollout.py --check` on its capture; fix the rendering until it reports equal, and record the ollmcp version it passed with
- [ ] 6.2 With the user's agreement: run the current code's baseline stages, full rollouts of the dev and held-out sets and a single-step stage of the dev set; record the time per sample and adjust the default sample counts in D7 and `docs/mcp-eval.md` if needed; record the baseline figures (held-out as counts only) in this design
- [ ] 6.3 Verify the comparison end to end: compare the dev baseline with a second dev stage of the same code and check the set's verdict is `within noise`; record it in this design

## 7. Docs and checks

- [ ] 7.1 Write `docs/mcp-eval.md` (D10): what is measured and why, setting up (Ollama with an 8192 context, the ollmcp venv, the demo), each command with an example, the question sets and the held-out rule, the adoption rule, the measured costs and the fidelity check's last passing version; verify every command shown against its `--help`
- [ ] 7.2 Update CLAUDE.md (`scripts/mcp_eval/` in the architecture, the commands, a line in the MCP section that wording and result changes are adopted by the `mcp-evaluation` rule and that held-out transcripts aren't read) and the comment on `_ONE_PHRASE` in `mcp_server.py` to point to it; verify `ruff check` and `tests/test_mcp_server.py` pass
- [ ] 7.3 Run `pytest`, `JOBHUNT_TEST_PG_URL=… pytest`, `ruff check`, `jobhunt privacy-check` and `openspec validate add-mcp-eval --strict`, and verify all pass
