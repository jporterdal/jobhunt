## 0. Prerequisites

- [x] 0.1 Confirm the starting point: the Alembic head is `0005_profile`, no other change in `openspec/changes/` modifies `skill-linking`, `profile-extraction` or `enrichment-evaluation`, and `pytest` passes before any edit. Verify with `alembic history`, `openspec list`, and a passing `pytest` run. If any differ, stop and tell the user.
- [x] 0.2 Copy `data/jobhunt.db` to `data/jobhunt.pre-0006.db` before anything migrates the real database. Verify that the copy exists and that `sqlite3` opens it read-only.

## 1. Schema (D8)

- [x] 1.1 In `db.py`, add `skill_expansions` and `link_measurements` (to `DERIVED_TABLES`, with comments in the style of the existing ones) and `profile_merges.rephrase`. Verify that `python -c "import jobhunt.db"` succeeds and that each new table is in exactly one table list.
- [x] 1.2 Generate `0006_skill_expansion` against a scratch database at head (CLAUDE.md, "Schema migrations"). Write `downgrade()` per D8, including stripping ` rephrase` from queued document jobs. Verify with `pytest tests/test_migrate.py` on SQLite and Postgres, plus a test that a downgrade from `0006` leaves a queued document job's pipeline without the suffix.

## 2. Expansion step and context (D1, D2)

- [x] 2.1 Add `enrich/expand.py`: the `skill-expand@1` prompt, the `phrases` schema, cleaning, and a step that returns phrasings or raises `StepFailed`. Add `phrases` answers to `FakeLLM`. Verify with unit tests for the spec scenario "Duplicate phrasings dropped", the eight-word limit, the six-phrasing cap, and that the request includes the context quote ("Ambiguous name read in context").
- [x] 2.2 Add `derived.save_expansion` and the expansion lookups (posting: newest succeeded at the step, any context; profile: newest succeeded at the step with equal context). Verify with tests that a second posting quote doesn't cause a new expansion ("Expanded once") and that a failed expansion isn't returned by the lookup.
- [x] 2.3 Add `queries.expansion_contexts` (D2 order, through `profile_merge_changes`), and make the judge's candidate quotes use it instead of `links.evidence_quotes`. Verify with tests for the `skill-linking` scenarios "Evidence from a later document doesn't change phrasings", "Rewriting phrasings from a document", "Rolling back the rewriting merge" and "A skill added by hand", driven through `merge_run` and `rollback_merge`.
- [x] 2.4 Carry the option through the backend: `jobs.enqueue_document(..., rephrase=)` appends ` rephrase` and widens a queued job, `cv.check_pipeline` accepts it, `_run_document` passes it to `userdata.merge_run(conn, run_id, rephrase=)`, which stores `profile_merges.rephrase`, and "merge again" reuses the stored value. Verify with tests for widening a queued job, the stored flag after a job runs, and "merge again" keeping it.

## 3. Phrase-pair similarity, method registries and the links job (D3, D4, D6)

- [x] 3.1 Add the candidate-finding registry (`names`, `skill-expand@1`, each with its size and floor), the judge registry (`link-judge@2` as today), `CURRENT_RETRIEVAL = "names"`, `CURRENT_JUDGE = "link-judge@2"`, and the pipeline id built from them. Verify with a test that the pipeline id is still exactly `links=link-judge@2`, and that the existing link tests pass unchanged.
- [x] 3.2 Implement phrase-pair shortlisting: normalised vectors, max over pairs, the name always a phrase, and `pair` recorded in `candidates_json`. Verify with a test for the spec scenario "Similar meaning, different spelling" using `FakeOllama` vectors, and that `names` shortlists are identical to today's.
- [x] 3.3 Extend the links job per D6: expand (only when the current method expands, cancellable between requests), embed phrases, plan with the pipeline check, judge. Verify with tests for "Failed expansion" (name only, retried next job), "New linking method version" (re-judged, old link in effect until replaced), "Nothing changed", and that changing the chat model neither re-expands nor re-judges.
- [x] 3.4 Add `jobs.enqueue_links_if_outdated` and call it from `serve` after `jobs.recover`, outside the reloader's parent. Queue links judging when the user adds or removes evidence. Verify with tests for "New linking method version" (queued at start-up) and "Start-up with nothing to re-judge", plus an evidence trigger test.

## 4. `link-judge@3` (D5)

- [x] 4.1 Register `link-judge@3` with the revised prompt beside `@2` (not current). Verify with a request-content test (definitions of `none` and `general`, no "most are none", the ladder over linked relations only) and a test that none of its example pairs match an override in the test fixtures.

## 5. Link measurement (D7)

- [x] 5.1 Add `enrich/link_eval.py`: the reference set, and the plan with request counts (expansions, embeddings, judgments) and reuse from `link_measurements`, then `link_judgments` (ordered candidate list). Verify with tests for "Building the reference set", "Reusing the app's judgments", `--fresh` reusing expansions but not judgments, and "Stating requests first".
- [x] 5.2 Implement execution and scoring: the five judging counts, kept refusals, the right-skill-added judgments, the size and floor sweep, verdicts, differing posting skills, and the preview. Store results with `derived.save_measurement` as they're made. Verify with tests for "A missed candidate", "Sweeping sizes and floors", "Judging on its own shortlist", "Right skill added", "Refusal kept", "Better on links, same on refusals", "Mixed" and "Previewing a candidate method".
- [x] 5.3 Verify the separation: a test that measurement judgments never change `effective_links` or the plan ("Measuring doesn't change links", "Measuring a candidate version").
- [x] 5.4 Add `eval --links` to `cli.py`, with `--retrieval`, `--judge`, `--dry-run`, `--all-skills`, refusing `--skills` and `--segmenter`, plus the text and JSON reports. Verify with CLI tests for "Unknown version", "No overrides", Ollama unreachable after stating requests, and "Link measurement instead" in `enrichment-evaluation`. Also run `jobhunt eval --links --dry-run` against the real database (no GPU).

## 6. Measure and adopt (needs the user and the GPU)

- [x] 6.1 Check by hand that `link-judge@3`'s examples share no pair with the user's real overrides. Suggest that the user add the recurring unlinked skills they haven't labelled yet (LLMs, LLM APIs, Prompt engineering, Data analysis, data science, LLM evaluation, fine-tuning) on `/profile/links` first. Verify that the user has answered.
  - *Done 2026-10-06 without the user, who was away for the session:* the examples were checked by hand against the 55 real overrides. `@3`'s draft reused `@2`'s "Java" for "C#", which is an override, so it and every example naming an override's posting skill were replaced. Nothing was suggested for labelling.
- [x] 6.2 Run `jobhunt eval --links --retrieval names,skill-expand@1 --judge link-judge@2,link-judge@3 --dry-run`, report the request counts, and **ask the user before running it without `--dry-run`**. Verify that the `names` + `link-judge@2` figures match the handoff's baseline for the overrides that existed then (25/28 shortlisted, 22/28 right, all refusals kept), and explain any difference.
  - *Done 2026-10-06.* The user allowed GPU use for the session in advance. The dry run stated 98 expansions and 3/41/≤79/≤79 judgments. The baseline is 26 of 29 shortlisted, 23 right and 21 of 21 refusals kept: the handoff's figures plus one more reference link (design.md, "Measurement results").
- [x] 6.3 With the user, read the report, choose `skill-expand@1`'s size and floor from the sweep, re-run with them, and decide what to adopt by the proposal's rule. Verify by recording the decision and the figures in this change's design.md under D3 and D5.
  - *Done 2026-10-06 without the user reading the report.* Every candidate is `worse`, so nothing was adopted and no size or floor was chosen (design.md, "Measurement results").
- [x] 6.4 If expansion or `@3` isn't adopted, stop and revise this change's artifacts with `/opsx:update` before continuing. Otherwise set `CURRENT_RETRIEVAL` / `CURRENT_JUDGE` to the adopted ones and delete the superseded registry entries. Verify that `pytest` passes with the tests updated for the new pipeline id `expand=skill-expand@1 links=link-judge@3`.
  - *Stopped here 2026-10-06: neither expansion nor `@3` is adopted.* The app stays on `names` + `link-judge@2`, and both candidates stay registered but unused. The artifacts need `/opsx:update` with the user, which also decides group 7 and how much of expansion stays: the `skill-linking` and `profile-extraction` deltas describe expansion as app behaviour.
  - *Later on 2026-10-06, with the user's approval:* the verdict became a paired comparison with a sign test (`better`/`worse` only at p ≤ 0.05, else `within noise`), ties with the user's choice are counted apart, and the app's judge became `link-judge@5` (`@2` with neutral examples; design.md, "Third round"). Still open for `/opsx:update`: which measured methods stay registered, the expansion deltas, and group 7.
  - *Fourth round, 2026-10-06:* `link-judge@6` (the CV line beside each profile skill) measured on 46 links and 32 refusals after the user's profile cleanup: within noise of `@5`; expansion again worse. Not adopted (design.md, "Fourth round").
  - *Revised with `/opsx:update`, 2026-10-06, with the user:* the app keeps `names` + `link-judge@5`. `skill-expand@1` + `@5` and `names` + `@6` stay registered for later measurement, and the rest is deleted (6.5). Group 7 is dropped: the rephrase choice stays in the backend only. The `skill-linking` deltas now describe expansion as a measured method, and the `profile-extraction` delta was removed (design.md, "Decision at the end of the change").
- [x] 6.5 Delete `link-judge@2`, `@3` and `@4`, `matched@1` and `matched-trim@1` from `links.py`, with the code only they use: the matched-mean score, drift trimming, `PairJudge` and the pair-answer reuse in `link_eval.py`. Keep `names`, `skill-expand@1`, `link-judge@5` and `@6`, and `@5`'s prompt text unchanged. Update the tests that measured or registered the deleted entries. Verify that `pytest` passes, that `jobhunt eval --links --judge link-judge@2` names `link-judge@5, link-judge@6` as available, and that `jobhunt eval --links --retrieval names,skill-expand@1 --judge link-judge@5,link-judge@6 --dry-run` runs against the real database (no GPU).
  - *Done 2026-10-06.* `@5`'s and `@6`'s prompts are byte-identical to before. 706 tests pass on SQLite (7 tests of deleted code removed). The dry run states 0 requests for every combination except `skill-expand@1` + `@6` (90 judgments).

## 7. The option in the web interface (D2): dropped

- 7.1 *Dropped 2026-10-06, with the user.* The app's method doesn't expand, so a "Rewrite skill phrasings from this document" checkbox would change nothing visible. The backend keeps the choice (2.4), and the `skill-linking` spec says the web interface doesn't offer it ("No choice offered"). A change that adopts expansion adds the checkbox.

## 8. Docs and wrap-up

- [x] 8.1 Update CLAUDE.md:
  - the expansion step and context rule
  - the link pipeline id
  - one linking method, with re-judging after a version change and at start-up
  - `eval --links` in Commands
  - the rephrase choice (backend only, no checkbox)
  - the `0006` backup note
  - the known weak spots after measuring.

  Verify that every command listed there runs.
- [x] 8.2 Run `pytest` on SQLite and with `JOBHUNT_TEST_PG_URL`, and `openspec validate improve-skill-linking --strict`. Verify that both pass.
  - *Done 2026-10-06:* 706 passed on SQLite (424 Postgres-only skipped), 1130 passed with `JOBHUNT_TEST_PG_URL`, and the change is valid.
- [x] 8.3 Add the follow-ups from design.md, "Decision at the end of the change", to `FUTURE_CHANGE.md` as a new section. Verify that the section names each one with its figures and the code it would touch.
