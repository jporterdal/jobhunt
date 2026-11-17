## Why

`add-mcp-eval` asks every question after the questions before it, so a question's result can't be split between its own wording and its history. dev-2 passed 2 of 10 rollouts in both dev baselines (it passed 3 of 3 in sessions), and in 23 of 30 single steps the first search kept the `workplace` filter left by dev-1. Whether the question, the earlier answer or the earlier filter causes that is unknown, and the next wording change (a statement about a leftover `workplace` filter) depends on knowing it. The measurement's terms (rollout, sample, session, stage) are also defined only in specs and designs, which a reader of `docs/mcp-eval.md` shouldn't need to open.

## What Changes

- **History conditions** for rollouts (`rollout.py --history`), recorded with each stage:
  - `fixed` (the default, today's rollouts): the earlier questions of the set with their hand-written `history_answer`s;
  - `own` (new, as rollouts): a chain asks the set's questions in order and each answer the model gives becomes history for the next, as in a session but without the client;
  - `none` (new): each question alone, with no earlier messages.
- **Order**: the set's order stays the default. `--order balanced` (new) runs a one-off evaluation in a balanced order instead (a Williams design: for five questions, ten orders, order *k* for sample *k*, so each question is asked twice in each position and twice after each other question), at no extra cost per sample.
- **Comparing conditions** (new): `compare.py --conditions` compares two stages of the same code that differ only in history or order, with the same exact test, and reports each question's history (or order) effect. A comparison of two code versions refuses stages of different conditions.
- **Adopting a wording or result change** now needs both a `fixed` and a `none` comparison against the current code: the dev set `better` in at least one of them, no dev question `worse` in either, and the held-out set not `worse` in either; the session batch is still required.
- **Resuming** covers the new conditions: a stopped `own` stage continues its unfinished chains from the answers already recorded.
- **Docs**: `docs/mcp-eval.md` opens with direct definitions of *question set*, *history*, *rollout*, *single-step rollout*, *chain*, *session*, *sample* and *stage*, and describes the conditions, the order options (fixed by default, balanced for one-offs) and the new rule. CLAUDE.md's MCP lines follow.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `mcp-evaluation`: rollouts gain history conditions and a balanced order; question sets must read without history; the report and the comparison of code versions name the stage's conditions; a comparison of conditions on the same code is added; the adoption rule adds the no-history condition.

## Impact

- **Changed:** `scripts/mcp_eval/` (`common.py`, `rollout.py`, `score.py`, `compare.py`; `batch.py` records its sessions' condition), `tests/test_mcp_eval.py`, `docs/mcp-eval.md`, CLAUDE.md.
- **Unchanged:** `src/jobhunt/` (the MCP server and the package), the question sets' contents, sessions' behaviour.
- **Earlier stages** (`baseline-dev`, `baseline-dev-2`, `baseline-holdout`, `first-dev`) have no condition in `stage.json`; they read as `fixed` in the set's order and stay the `fixed` baselines. New `none` baselines (dev and held-out) are measured on the GPU, with the user's agreement.
- **GPU:** each code version now needs a `none` stage of each set as well, about 40 more minutes a version.

## Parser impact

None: see [parser-impact.md](parser-impact.md).
