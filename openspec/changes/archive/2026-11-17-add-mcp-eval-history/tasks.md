## 1. Conditions and orders in common ground

- [x] 1.1 Add the conditions to `common.py` (D1): `HISTORIES = ("fixed", "own", "none")`, `ORDERS = ("set", "balanced")`, `stage_info` taking `history` and `order` (and `orders` for balanced), and a reader that gives a `stage.json` without them `fixed`/`set` (sessions `own`); verify in `tests/test_mcp_eval.py` that an old stage file reads as `fixed`/`set` and `batch.py`'s stage info records `own`
- [x] 1.2 Add `williams(ids)` to `common.py` (D4): rows from `0, 1, n−1, 2, n−2, …` shifted by 1 a row, mirrored rows added when n is odd; verify for 5 and 4 questions that each question is in each position equally often and directly follows each other question equally often, and that 5 gives 10 rows
- [x] 1.3 Generalise `common.history` to take the questions before a question in a given order (the set's order unchanged by default); verify the existing history test still passes and a row's history is the questions before it in that row

## 2. Rollouts under each condition

- [x] 2.1 Add `--history` and `--order` to `rollout.py` with the refusals of D2–D4 (`balanced` with `none`; `--questions` and `--first-step` with `own`), the conditions and orders in the statement, and the "isn't balanced" statement when the sample count isn't a multiple of the rows; verify each refusal exits 2 with nothing sent, and the dry run names the conditions
- [x] 2.2 Implement `none` (D2): each first request holds only the question; verify against the stub that every request's first message is the question and there is no other earlier message, for full and `--first-step` stages
- [x] 2.3 Implement `fixed` under a balanced order (D4): sample k uses row (k−1) mod rows, each record carries its row, `stage.json` the rows; verify against the stub that sample k's first request holds the questions before it in row k with their `history_answer`s
- [x] 2.4 Implement `own` chains (D3): chain k asks the questions in the stage's order, appends each answered question's final content as history (left out when empty, the question left out when stopped at the loop limit), records `chain` and `position`; verify against a stub that answers each question with a distinct text that the second question's request holds the first answer, and that a question the stub keeps calling tools on is absent from later history
- [x] 2.5 Extend `--resume` (D8): the conditions and rows are stage options; an `own` stage resumes an unfinished chain at its first unrecorded question with its recorded answers as history; verify an `own` stage interrupted after a chain's first question resumes with that answer in the next request, and that giving `--history` or `--order` with `--resume` is refused

## 3. Report, detail and comparison

- [x] 3.1 Update `score.py` (D7): the header names history and order; a `none` stage reports `unasked_filter` instead of `carried_filter`; "every question passed" says "paired by chain" for `own`; an unfinished balanced stage is flagged; verify on hand-made stages of each condition
- [x] 3.2 Update `detail.py` (D7): a sample's condition and, for balanced and `own` samples, the questions before it; the held-out refusal unchanged; verify on a hand-made `own` held-out stage that the refusal still shows nothing
- [x] 3.3 Update `compare.py` (D5): code comparisons refuse different `history` or `order` and name the condition in the header; `--conditions A B` requires equal code hashes, sets, models and kinds and differing conditions, gives `more`/`fewer`/`within noise` with both p-values and no set verdict; verify each refusal and the verdicts on hand-made scores (2/10 against 9/10 gives `more`)

## 4. Docs

- [x] 4.1 Update `docs/mcp-eval.md` (D9): the glossary before the commands (question set, history and its conditions, rollout, single-step rollout, chain, session, sample, stage, order); the conditions and what each tells; the set's order as default and `--order balanced` for one-off evaluations; `compare.py --conditions`; the new adoption rule with its costs; verify every command shown against its `--help`
- [x] 4.2 Update CLAUDE.md (the MCP measurement commands and the adoption-rule line) and the `mcp-evaluation` references in `scripts/mcp_eval/` docstrings; verify `ruff check` passes

## 5. Measuring (on the user's GPU, only with their agreement)

- [x] 5.1 With the user's agreement: run full `none` stages of the dev and held-out sets on the current code (the `fixed` baselines of `add-mcp-eval` stand while the code hash is unchanged); record the figures (held-out as counts only) and the time per sample in this design
- [x] 5.2 Compare `baseline-dev` with the dev `none` stage using `compare.py --conditions`, and record each dev question's history effect in this design (dev-2 in particular)

## 6. Checks

- [x] 6.1 Run `pytest`, `JOBHUNT_TEST_PG_URL=… pytest`, `ruff check`, `jobhunt privacy-check` and `openspec validate add-mcp-eval-history --strict`, and verify all pass
