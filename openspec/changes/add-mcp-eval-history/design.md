## Context

See proposal.md for why. What exists (`add-mcp-eval`, archived as `openspec/changes/archive/2026-11-16-add-mcp-eval/`):

- **Rollouts** (`rollout.py`): a question's messages are `common.history(questions, index)` (each earlier question with its `history_answer`) and then the question; tools come from the working tree's server in-process; the loop stops at an answer or after 7 rounds. One record a sample in `samples.jsonl`; `stage.json` holds kind (`rollout`, `first-step`), set, questions, samples, model, Ollama version, code hash, `set_sha256` and the tools. `--resume` continues a stopped stage with its own options and is refused when the code, the set's questions, the tools or the Ollama version changed.
- **Sessions** (`batch.py`, `session.py`): ollmcp asks the set in order, so each question's history is that session's own earlier answers (a question stopped at the loop limit isn't kept). Kind `session`.
- **Scoring** (`score.py`): `records()` assigns each request to a question by its last user message, so it doesn't depend on what came before. A full stage scores every check but `first_call`; a single-step stage only `first_call`. `carried_filter` counts searches using one of a question's `unasked_filters`. "Every question passed" pairs samples by number.
- **Comparison** (`compare.py`): per question, one-sided Fisher tests at p ≤ 0.05; refuses stages of different sets, kinds or models; warns on equal code hashes, different Ollama versions and different sample counts.
- **Baselines** (2026-11-16, code `32fc4e357c78`): `baseline-dev`, `baseline-dev-2`, `baseline-holdout` (full, history as written), `first-dev` (single step). dev-2 passed 2/10 in both dev stages; its first search kept `workplace` in 23 of 30 single steps.
- **The ten questions** all name what they ask about (a posting by title and company, a company, a URL number, the profile, "saved remote postings", "shortlisted postings"), so each reads on its own.

## Goals / Non-Goals

**Goals:**
- Tell a question's wording apart from its history: the same questions asked with written history, with the model's own history, and with none, and a comparison between them on the same code.
- Make the set's order something that can be varied for a one-off check, without making it the default or adding cost.
- Adopt wording changes on evidence from both the no-history and the written-history conditions.
- Define the measurement's terms in `docs/mcp-eval.md` itself.

**Non-Goals:**
- Changing the MCP server, the question sets' questions or their checks.
- Varying the order of sessions (three or so sessions can't balance five positions); sessions keep the set's order.
- A correction for testing several questions and two conditions at once (Risks).
- Comparing `own` chains with sessions as a fidelity measure; `rollout.py --check` stays the fidelity check.

## Decisions

### D1. Conditions are stage attributes

A stage gets two more fields in `stage.json`: `history` (`fixed`, `own`, `none`) and `order` (`set`, `balanced`). A stage without them (every stage before this change) reads as `fixed` and `set`; sessions are `own` and `set`. They are stage options like the set and model: `--resume` takes them from `stage.json`, and the statement printed before any request names them.

`rollout.py --history fixed|own|none` (default `fixed`) and `--order set|balanced` (default `set`).

*Alternative considered:* new kinds (`rollout-none`, `rollout-own`). Kinds already mean "what is scored" (full or first call); mixing history into them would multiply them and make "same kind" mean two things in the comparison.

### D2. `none`: the question alone

The messages are only `{"role": "user", "content": <question>}`; tools, options and the loop are as for `fixed`. Single steps work as for `fixed` (`--first-step --history none`). The order has no meaning without history, so `--order balanced` with `--history none` is refused.

Every question must read on its own (spec "Question sets"); the ten current ones do (Context). With no history, a search filter from `unasked_filters` wasn't carried from anything, so in a `none` stage the report names the diagnostic `unasked_filter` (same count, same rule) rather than `carried_filter`.

### D3. `own`: chains

A **chain** is one pass through the set in the stage's order, as a session is: each question is asked after the earlier questions of the chain with the answers the model gave them, built by the same rules `rollout.py --check` already uses for a capture (the final reply's content as an `assistant` message, left out when empty; a question stopped at the loop limit left out of the history). Chain *k* gives sample *k* of every question, so pairing samples by number is real here, as in sessions.

Each sample record gets `chain` (= its sample number) and `position`. `--questions` is refused with `own` (a chain of only some questions would change their history), and so is `--first-step` (a first request needs the chain's earlier answers, which a single-step stage doesn't produce). `own` is a diagnostic: it shows what the model's own answers do to later questions at rollout speed, which sessions show only three at a time.

*Alternative considered:* using sessions as the only `own` condition. They stay the confirmation through the real client, but at 3–6 a batch they can't attribute a failure to history.

### D4. Balanced order: a Williams design

For *n* questions, the rows are built from the first row `0, 1, n−1, 2, n−2, …`, each next row adding 1 modulo *n*; when *n* is odd, the mirrored rows (each row reversed) are added, giving 2*n* rows (10 for five questions), otherwise *n*. Across the rows each question is in each position equally often and directly follows each other question equally often (twice each for five questions). Sample *k* uses row (*k* − 1) mod rows. `stage.json` records the rows as question ids (`orders`) and each sample record its row, so a reader can see each sample's history.

- **History under an order:** for `fixed`, a question's history is the questions before it in its sample's row, with their `history_answer`s; with `--questions`, unselected questions still count as history, as they do in the set's order today. For `own`, the chain asks the questions in the row's order.
- **Balance needs whole rows:** with a sample count that isn't a multiple of the rows, the statement says the stage isn't balanced and by how much; it still runs.
- **Cost:** none. A `fixed` sample costs the same whatever its position, and the default 10 samples are exactly the 10 rows for five questions.
- **Default stays `set`:** the set's order keeps the designed carry-overs (holdout-1's `tag` hiding holdout-2's posting) in every sample. In a balanced stage, holdout-2 follows holdout-1 in only 2 of 10 samples. Balanced stages are one-off evaluations, for example "does dev-2 fail wherever it sits, or only after dev-1".

*Alternative considered:* random orders with a seed. They balance only on average; at 10 samples a question could sit in one position three or four times, and two stages compared would need the same seed anyway. The user chose Williams only.

### D5. Comparing conditions

`compare.py --conditions A B` compares two stages that ran the same code (equal code hashes), set, model and kind, and differ in `history` or `order` (refused otherwise, including when nothing differs). It uses the same per-question exact test; the verdicts are named for what they measure, `more` (B passes more often), `fewer` or `within noise`, with both p-values, and the header names the conditions ("history none against fixed"). There is no set verdict: it's an attribution, not a decision.

A comparison of code versions (the default) now also refuses stages whose `history` or `order` differ, and names the condition in its header.

### D6. The adoption rule

For a wording or result change, the candidate and the current code each have four full rollout stages with the same model: `fixed` and `none`, dev and held-out, each in the set's order. The change is adopted only when:

1. the dev set is `better` in at least one condition;
2. no dev question is `worse` in either condition;
3. the held-out set isn't `worse` in either condition;
4. a session batch with the change shows no question that rollouts passed failing in every session.

*Why one, not both, conditions `better`:* a fix for something history causes (a carried `workplace` filter) can't show without history, and a fix to how a question alone is read may be masked by history. Requiring both would block the first kind. Requiring no `worse` in either keeps a fix in one condition from being paid for in the other. The current code's stages are reused while its code hash is unchanged, so a candidate costs about 40 more minutes than under the old rule.

### D7. Report and detail

`score.py` prints the stage's `history` and `order` in its header, `unasked_filter` for `none` stages (D2), and labels the "every question passed" line "paired by chain" for `own`. `detail.py` prints a sample's history condition and, for `fixed` under a balanced order and for `own`, the questions before it. The held-out discipline is unchanged: in an `own` chain of the held-out set, the model's held-out answers are history for later held-out questions and are never printed.

### D8. Resuming

The rules of `--resume` stay, with `history`, `order` and `orders` among the stage's own options. An `own` stage stopped mid-chain continues that chain at its first unrecorded question, with the chain's recorded answers (from `samples.jsonl`) as history. A sample cut off by a kill is still dropped and run again.

### D9. Terms in the docs

`docs/mcp-eval.md` opens with a short glossary, so nobody needs the specs:

- **question set**: dev or held-out, five questions in a fixed order with their checks;
- **history**: the messages a question is asked after (the condition: `fixed`, `own`, `none`);
- **rollout**: one simulated attempt at one question, sending Ollama the client's requests without the client, with tools answered by the working tree's server in-process; **single-step rollout**: only its first request;
- **chain**: rollouts of a whole set in order, each answer becoming history for the next (`own`);
- **session**: the real client (ollmcp) driven in a terminal through a capture proxy, asking the whole set;
- **sample**: one attempt at one question, scored pass or fail (a rollout, or a question's part of a chain or session);
- **stage**: a batch of samples of one code version, set, model, kind and condition, in its own folder;
- **order**: the set's order (default) or balanced (one-offs).

It then says which condition does what, that the set's order is the default and `--order balanced` is for one-off evaluations, and gives the new adoption rule and costs. CLAUDE.md's MCP measurement lines and commands follow.

### D10. Tests

In `tests/test_mcp_eval.py`, without a model (the stub Ollama on loopback):

- `none`: each request holds one message, and `--order balanced` with it is refused.
- `own`: the second question's first request holds the first question's answer from the stub as history; a question stopped at the loop limit isn't in later history; `--questions` and `--first-step` are refused with it.
- Williams rows: for 5 (and 4) questions, every question in every position equally often and each ordered neighbouring pair equally often; sample *k*'s first request under `fixed` follows row *k*; a sample count that isn't a multiple is stated.
- Comparison: code comparison refuses different conditions; `--conditions` refuses different code hashes or equal conditions, and gives `more`/`fewer` on hand-made scores.
- Resume: an `own` stage interrupted mid-chain resumes that chain with the recorded answer as history; old `stage.json` files without the fields read as `fixed`/`set`.
- Report: the header names the conditions; a `none` stage reports `unasked_filter`.

## Risks / Trade-offs

- **More chances of a false `better`.** Two conditions double the chances of a chance `better` on some dev question. → No question may be `worse` in either, the held-out set mustn't be `worse` in either, and a session batch must agree.
- **`fixed` history isn't the model's.** Unchanged from `add-mcp-eval`. → `own` chains now measure that at rollout speed, and sessions still confirm.
- **`none` may be unnatural for later questions** (a question that refers to "those postings"). → The spec requires every question to read on its own; a question that can't isn't added to a set.
- **Balanced stages have more spread.** A question's samples come from ten histories, so its pass count varies more and a smaller effect goes unseen. → Balanced is for one-off attribution, not adoption.
- **Partly balanced stages.** A stopped balanced stage, or a sample count that isn't a multiple of 10, leaves positions uneven. → Stated before running; `score.py` says when a balanced stage is unfinished.
- **GPU time.** About 40 more minutes for each code version measured. → The current code's stages are reused while its code is unchanged; `--questions` narrows `fixed` and `none` stages to the questions a change is about.

## Migration Plan

Old stages read as `fixed`/`set` and remain the `fixed` baselines for code `32fc4e357c78`. With the user's agreement, `none` baselines of the dev and held-out sets are measured once the scripts are in, and recorded in this design (held-out as counts). Rollback is reverting the scripts; stages written with the new fields are still read by the old scripts except for their conditions.

## Measurements (2026-11-16)

Code `32fc4e357c78` (unchanged since `add-mcp-eval`'s baselines, which stand as the `fixed` stages), `qwen3:8b` wholly in VRAM, an 8192 context, Ollama 0.32.1, full rollouts in the set's order, 10 samples a question. The `none` stages are `none-dev` and `none-holdout`.

**Time.** `none-dev`: 50 samples in 28.5 min, 34 s a sample (`baseline-dev`: 38.8 min, 47 s). `none-holdout`: 34.3 min, 41 s a sample (`baseline-holdout`: 28.4 min, 34 s). Without history the dev prompts are shorter and dev-3 makes fewer calls; the held-out set was slower, its questions making more calls on their own (holdout-5 three a sample). A `none` stage of a set costs about as much as its `fixed` stage, so the new rule's extra cost is about 30–35 minutes a set and code version, as D6 estimated.

**Dev, `compare.py --conditions baseline-dev none-dev`** (history none against fixed). The difference is none's pass rate minus fixed's, with a 95% Newcombe score interval. Mid-p is one-sided, for "none passes more often"; the other direction is 1 − mid-p. Fisher's p is what `compare.py` reports.

| Question | fixed | none | Difference [95% interval] | mid-p | Fisher p |
|---|---|---|---|---|---|
| dev-1 | 10/10 | 10/10 | 0 | 0.500 | 1.000 |
| dev-2 | 2/10 | 6/10 | +0.40 [−0.02, +0.67] | 0.047 | 0.085 |
| dev-3 | 6/10 | 6/10 | 0.00 [−0.37, +0.37] | 0.500 | 0.675 |
| dev-4 | 10/10 | 10/10 | 0 | 0.500 | 1.000 |
| dev-5 | 7/10 | 9/10 | +0.20 [−0.16, +0.51] | 0.167 | 0.291 |

At 10 samples a question, each estimate is imprecise: every interval is 0.6–0.75 wide. `compare.py` gives every question `within noise`, because its verdicts compare Fisher's p with 0.05. Those verdicts are read here as estimates and evidence instead (a later change replaces them).

**dev-2's history effect.** dev-2 moves the most, +0.40 (mid-p 0.047): moderate evidence that its history lowers its pass rate. Its diagnostics move with it, which suggests a mechanism. A `workplace` filter appeared in 7 of 10 `fixed` samples (`carried_filter`) and in 1 of 10 `none` samples (`unasked_filter`). Invented arguments fell from 8 to 2 samples, URL numbers as `job_id` from 3 to 0, and refused calls from 3 to 0. Titles and companies combined in one `q` stayed at 5 of 10 in both. So the history, mostly the filter carried from dev-1, looks like part of dev-2's failure, but its wording alone still fails 4 of 10 times, half of them with a combined `q`. A wording change aimed at the carried filter can only show under `fixed`, which D6 allows. dev-3 shows no sign of a history effect (equal counts), though its interval doesn't rule out a moderate one in either direction. dev-5 gives weak evidence in the same direction as dev-2.

Every question passed in 4 of 10 `none` samples (0 of 10 under `fixed`). Under `none`, samples of different questions aren't linked, so this figure follows from the per-question rates (about 3 of 10 expected) and isn't separate evidence. The `fixed` figure reflects dev-2's 2 of 10.

**Held-out, `compare.py --conditions baseline-holdout none-holdout`** (pass counts only): holdout-1 1/10 → 3/10, holdout-2 3/10 → 6/10, holdout-3 0/10 → 1/10, holdout-4 10/10 → 10/10, holdout-5 1/10 → 4/10. Every question that differed passed more often without history, by 0.1 to 0.3 (mid-p 0.08 to 0.25 each). That points the same way as dev, but each question's evidence is weak, and the four aren't combined into one test.

## Open Questions

- Whether a balanced-order or `own` result should ever count toward adoption. For now neither does (D6).
