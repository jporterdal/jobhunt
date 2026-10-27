## 0. Prerequisites

- [x] 0.1 Confirm the starting point: the Alembic head is `0006_skill_expansion`, no other change in `openspec/changes/` modifies `posting-enrichment`, `skill-linking`, `llm-connection` or `enrichment-evaluation`, and `pytest` passes before any edit. Verify with `alembic history`, `openspec list` and a passing `pytest` run. If any differ, stop and tell the user.
- [x] 0.2 Confirm with the user that the 9 labelled postings lose their suggestions until re-extracted (design D2), rather than the `atomic@2 … v@3` eval runs being adopted as app runs. Verify by recording the answer in design.md D2. If they choose adoption, change task 1.2's backfill to match before writing it.
- [x] 0.3 Copy `data/jobhunt.db` to `data/jobhunt.pre-0007.db` before anything migrates the real database. Verify that the copy exists and opens read-only.

## 1. Schema (D1, D2)

- [x] 1.1 In `db.py`, add `origin` to `posting_enrichments` (Text, not null, server default `'app'`, with a comment in the style of `posting_skill_marks.origin`). Verify that `python -c "import jobhunt.db"` succeeds.
- [x] 1.2 Generate `0007_run_origin` against a scratch database at head (CLAUDE.md, "Schema migrations"). Add the backfill that sets `'eval'` on runs no `llm_jobs.enrichment_id` points at, and write `downgrade()` (drop the column). Verify with `pytest tests/test_migrate.py` on SQLite and Postgres, plus a migration test: a database at `0006` with one job-linked run and one unlinked run upgrades to one `app` run and one `eval` run.

## 2. Writers record origin (D1)

- [x] 2.1 Make `origin` a required argument of `derived.save_run`. Pass `'app'` from `jobs._run_posting` and `'eval'` from `evaluate.execute`. Verify with tests that a queued job's run is `app`, and that a run stored by `evaluate.execute` (FakeLLM) is `eval`.

## 3. App reads use app runs only (D3)

- [x] 3.1 Filter `queries._latest_successful_runs` to app runs. Verify with tests for the spec scenarios "Eval run stays out of the app" (posting skills and salary summary) and "Eval run left out" (`skill-linking`), including that `posting_skill_keys` doesn't list a skill only an eval run suggests.
- [x] 3.2 Make `queries.enrichment_panel` list and show app runs only, returning `None` when a posting has none. Verify with a test for "Only eval runs", and a web test that the posting page then has no "Model says" panel but still offers extraction.
- [x] 3.3 Make `queries.unextracted_ids` count only app runs as done. Verify with a test for "Eval run doesn't count as extracted".
- [x] 3.4 Make `userdata._acceptable_run` refuse eval runs. Verify with tests for "Eval run not acceptable" (single accept and accept-all), and "Marks from a run the app no longer uses" (accepted marks and rejections survive a run becoming `eval`).

## 4. One skill method (D4, D5)

- [x] 4.1 Rename `pipeline.DEFAULT_SKILLS` to `CURRENT_SKILLS`, remove `jobs.current_skills`, and use the constant in `current_pipeline`, `steps_for` and `evaluate.plan`. Verify that `grep -rn "DEFAULT_SKILLS\|current_skills" src tests` finds nothing and the existing jobs and eval tests pass.
- [x] 4.2 Delete `atomic@4` from `enrich/skills.py` (`SKILLS_SYSTEM_V4`, `EMPTY_REMINDER_V4`, `ATOMIC_V4`, its comments), leaving `EXTRACTORS = (ATOMIC_V2,)`. Add a test that the registry holds `CURRENT_SKILLS` and at most one other version. Verify with the "Default request unchanged" test still passing and `grep -rn "atomic@4\|V4" src` finding only migration-era comments, if any.
- [x] 4.3 Remove `llm.skills` from `userdata.DEFAULT_SETTINGS` and `set_setting`, and remove the field from `web/llm.py` and `templates/settings.html`. Verify with tests for "Choosing a skill extraction method" (no form field) and "Unknown method rejected" (a settings request naming `llm.skills` changes nothing and says so).
- [x] 4.4 Add a test-only candidate `atomic@5` (monkeypatching `skills.EXTRACTORS`) and rewrite the tests that used `atomic@4`. In `test_suggestions.py`, the settings cases go, replaced by 4.3's test. In `test_cli_eval.py`, the comparison tests use `atomic@2,atomic@5`, and a new test covers "Removed method" (`--skills atomic@4` exits 1, naming the available methods). In `test_jobs.py`, a queued job naming `atomic@4` fails with the pipeline in its error and stores no run ("Queued job naming a removed version"). Verify with `pytest`.
- [x] 4.5 Add an eval test for "Evaluating a candidate leaves the app alone": after `execute` stores `atomic@5` runs, `posting_skills`, `enrichment_panel` and `effective_links` return what they did before. Add one for "Reusing an app run" (no FakeLLM call when an app run matches). Verify with `pytest tests/test_eval*.py tests/test_cli_eval.py`.

## 5. Docs and full run

- [x] 5.1 Update CLAUDE.md:
  - Project status: one line for this change.
  - "Model enrichment": one skill method named by the code, a registered candidate is for measuring only, no Settings choice, and runs carry an origin that the app filters on.
  - Data kinds: `posting_enrichments` rows are app or eval runs, and only `evaluate.py` reads eval runs.
  - "Data and backups": going below `0007_run_origin` drops run origins, and eval runs reach the app again.
  - Commands: `--skills` takes the app's method and its candidate.
  Verify by reading the changed sections against the specs.
- [x] 5.2 Run `pytest`, and `JOBHUNT_TEST_PG_URL=postgresql+psycopg:///jobhunt_test pytest`. Verify both pass.

## 6. Real data (no model calls)

- [x] 6.1 Run `jobhunt serve` once (or `init_db`) on the real database so `0007` applies. Then recount read-only: runs by origin (expect 33 app, 45 eval), postings whose posting skills include suggestions (expect 32), and the 9 labelled postings' posting skills (marks only). Verify by reporting the counts to the user next to the 2026-10-06 figures.
- [x] 6.2 Recount FUTURE_CHANGE.md item 3's context figures (distinct posting skills, linked and unlinked) with the app's read models. Update that section, and delete item 2. Verify that FUTURE_CHANGE.md no longer mentions the leak as open. Tell the user that bulk extraction now offers the 9 labelled postings, without queuing them.
