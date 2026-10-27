## Context

See proposal.md for motivation. The current state this design builds on:

- **One writer, one table.** `derived.save_run` stores every posting run in `posting_enrichments`. Two code paths call it: `jobs._run_posting` (the queue), which then sets `llm_jobs.enrichment_id` to the new run, and `evaluate.execute` (`jobhunt eval`), which records nothing else.
- **Which run the app uses.** `queries._latest_successful_runs` (each posting's newest succeeded run on its latest snapshot, any model or pipeline) feeds `posting_skills`, and so `posting_skill_keys`, `effective_links` and link judging, and also `salary_summaries`. Three other paths look at runs on their own:
  - `queries.enrichment_panel` lists every run of the posting and shows the newest.
  - `queries.unextracted_ids` treats a posting as done when any succeeded run matches the current model and pipeline.
  - `userdata._acceptable_run` accepts from any succeeded run on the latest snapshot.
- **Skill versions.** `skills.EXTRACTORS = (ATOMIC_V2, ATOMIC_V4)`, `pipeline.DEFAULT_SKILLS = "atomic@2"`, and `jobs.current_skills` reads `llm.skills` (never stored in the user's database). `steps_from_id` raises `ValueError` for a pipeline whose steps are gone, and `jobs.run_next` already turns that into a failed job.
- **Stored data on 2026-10-06** (database at `0006_skill_expansion`):
  - 78 runs: 33 pointed at by posting jobs (32 `atomic@2 … v@3`, 1 `atomic@1`), and 45 eval runs (9 each of `atomic@1`, `atomic@2 v@2`, `atomic@2 v@3`, `atomic@3`, `atomic@4`).
  - The 9 eval-only postings are the 9 labelled ones. Each has 17–42 marks, 7–25 of them accepted from suggestions, and 4–23 rejections.
  - Posting jobs are never deleted (only the downgrade below `0005` deletes non-posting jobs).

## Goals / Non-Goals

**Goals:**
- The app's view of model output depends only on runs the app made, whatever `jobhunt eval` is run with (a skill method, `--model` or `--segmenter`).
- `jobhunt eval` keeps reusing every stored run, so measuring costs no more GPU than today.
- The app's skill method is a code constant, and the registry holds at most it and one candidate.

**Non-Goals:**
- Re-extracting the 9 labelled postings. The user does it from the posting list when they choose.
- Removing the segmentation-method or model settings. `--segmenter` and `--model` leaks are closed by run origin anyway.
- Scoring stored runs of deleted methods (`atomic@1`, `@3`, `@4`). Their runs stay in the database.
- Changing how the eval matches or scores (FUTURE_CHANGE.md item 1).

## Decisions

### D1. Record a run's origin on the run

Add `origin` to `posting_enrichments`: `'app'` or `'eval'`, not null, server default `'app'` (like `posting_skill_marks.origin`). `save_run` takes it as a required argument: `jobs._run_posting` passes `'app'`, and `evaluate.execute` passes `'eval'`.

*Alternatives:*
- **A measuring-only table set,** as `link_measurements` is for links. Not taken: runs have two child tables (`enrichment_skills`, `enrichment_salaries`), so every reader would need a second copy. The eval also reuses app runs, which would mean reading across both.
- **Use only runs whose model and pipeline are the app's current ones.** No migration, but changing the model in Settings, or any step version, would hide every existing suggestion until re-extraction. Also, `eval --segmenter rules` with the current model is a different pipeline from the app's only by accident of settings: the rule would show whatever matched. Origin says what actually happened.

### D2. Backfill from the job queue

Migration `0007_run_origin` adds the column with server default `'app'`, then sets `'eval'` on every run that no `llm_jobs.enrichment_id` points at. That is plain portable SQL (`UPDATE … WHERE id NOT IN (SELECT enrichment_id FROM llm_jobs WHERE enrichment_id IS NOT NULL)`). Downgrade drops the column. On the user's database this gives 33 app runs and 45 eval runs.

*Alternative:* adopt eval runs whose model and pipeline equal the app's current ones (the 9 `gemma4:12b`, `atomic@2 … v@3` runs) as app runs. With temperature 0 and a fixed seed their content is what the app would produce, so the 9 labelled postings would keep suggestions with no GPU work. Not taken: it records something that didn't happen, depends on the settings at migration time, and the postings it would help are the labelled ones, whose marks are already complete. **This is the decision most worth confirming with the user** (see Risks).

*Confirmed 2026-10-06:* the user chose the backfill as written. The 9 labelled postings lose their suggestions until they are re-extracted, and no eval run is adopted.

### D3. Every app read goes through app runs

- `_latest_successful_runs` adds `origin = 'app'`. This covers posting skills, links and salary summaries.
- `enrichment_panel` lists app runs only. A posting with only eval runs returns `None`, so it has no panel.
- `unextracted_ids` counts only app runs as done.
- `_acceptable_run` refuses an eval run with a `UserDataError` ("the run is not one the app uses").

Unchanged:
- `evaluate.reusable_run` and `first_run_at` read any origin. Reusing app runs is free measurement. Before this change eval runs were shown in the app, so a mark made after one may have been prompted by it, and the warning stays conservative.
- `rejected_suggestions` and marks are keyed by posting and skill, not by run, so they survive the switch.

### D4. One skill method, at most one candidate

- `pipeline.DEFAULT_SKILLS` becomes `CURRENT_SKILLS = "atomic@2"`.
- `jobs.current_skills` goes away, and `current_pipeline` uses the constant.
- `skills.EXTRACTORS` becomes `(ATOMIC_V2,)`. `SKILLS_SYSTEM_V4` and its reminder are deleted.
- `skill_extractors()` stays keyed by `name@version`, so a later candidate is one more entry. A test asserts that the registry holds the current method and at most one other.
- `evaluate.check_skills` names the registered methods, as it does now.

This mirrors `links.CURRENT_RETRIEVAL` / `CURRENT_JUDGE`.

*Alternative:* keep `atomic@4` as the registered candidate. Not taken: it was measured and not adopted. The linking rule ("a measured method that isn't adopted is deleted") applies, and the user chose to keep one version.

### D5. Settings lose the skill method

- Remove `llm.skills` from `userdata.DEFAULT_SETTINGS` and its `set_setting` branch. An unknown key is already refused with "unknown setting".
- Remove the form field (`web/llm.py`, `settings.html`).
- The migration doesn't touch `app_settings`. A stray `llm.skills` row elsewhere would be ignored, since settings are read through `DEFAULT_SETTINGS`.

### D6. Tests use a test-only candidate

Tests that used `atomic@4` (`test_suggestions.py`, `test_cli_eval.py`, `test_jobs.py`) register a candidate `atomic@5` by monkeypatching `skills.EXTRACTORS` (an `AtomicExtractor(5, …)` with a different prompt). A job test keeps the "queued pipeline names a removed version → failed" case, using `atomic@4`.

## Risks / Trade-offs

- **[The 9 labelled postings lose their unjudged suggestions]** → Their marks are complete labels, and the rest of the app works from marks. Bulk extraction now lists them (9 jobs of GPU work, started by the user). If the user would rather keep the suggestions with no GPU, D2's alternative is a one-line change to the backfill. Confirm before implementing.
- **[Posting-skill counts drop]** The `atomic@4` suggestions were most of the 9 postings' skills, so FUTURE_CHANGE.md item 3's figures shift → recount them read-only after the upgrade (no model calls).
- **[Link judgments for skills that no longer appear stay stored]** → Harmless: links are computed for current posting skills only, and re-judging only judges current keys.
- **[Downgrading brings the leak back]** → Documented in CLAUDE.md "Data and backups". The column holds nothing that can't be rebuilt from `llm_jobs`.
- **[A future writer forgets the origin]** → `save_run` has no default for it, so every caller must say which it is.

## Migration Plan

1. Back up `data/` (database and documents).
2. Ship `0007_run_origin`. `init_db` applies it at the next `import` or `serve`.
3. After upgrading, recount posting skills and links read-only, and compare with the 2026-10-06 figures (32 postings on `atomic@2`, 9 on `atomic@4`): expect 32 postings with suggestions, and the 9 labelled ones with marks only.
4. Rollback: `alembic downgrade 0006_skill_expansion` drops the column. Code from before this change ignores it either way.
