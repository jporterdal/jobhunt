## 1. Schema (D3)

- [x] 1.1 In `db.py`, add `app_settings`, `llm_jobs`, `posting_enrichments`, `enrichment_skills`, `enrichment_salaries` and `rejected_suggestions`. Add `importance` and `origin` (server default `'selection'`) to `posting_skill_marks`, and `skills_complete_at` to `posting_triage`. Add the user tables to `USER_TABLES`, and group the derived and operational tables as `DERIVED_TABLES` and `OPERATIONAL_TABLES`. Verify that `python -c "import jobhunt.db"` succeeds.
- [x] 1.2 Generate `0003_llm_enrichment` against a scratch SQLite database at head (CLAUDE.md "Schema migrations"). Review it for portability and write `downgrade()`. Verify that `pytest tests/test_migrate.py` passes on SQLite and Postgres, with no differences from `db.metadata`.
- [x] 1.3 Extend the migration test: a `0002` database with a skill mark, upgraded to head, has the mark with `origin = 'selection'` and `importance` NULL. Verify by running the test.

## 2. User-authored data (`userdata.py`)

- [x] 2.1 Add `get_setting` and `set_setting` with per-key validation:
  - `llm.model`: non-empty text
  - `llm.num_ctx`: an integer from 2048 to 131072, default 8192
  - `llm.segmenter`: a registered name, default `llm-lines`
  
  Verify with unit tests covering defaults, round trip and rejected values.
- [x] 2.2 Extend `add_skill_mark` with `importance` and `origin`. Add `set_mark_importance`. Verify with tests: marking with and without importance, changing importance leaves quote and origin unchanged, and invalid values raise `UserDataError`.
- [x] 2.3 Add `set_skills_complete(conn, job_id, complete)`, which sets or clears `skills_complete_at` through `_touch_triage`. Verify with tests for set, clear and an unknown posting.
- [x] 2.4 Add `reject_suggestion(conn, job_id, skill_name)` and `unreject_suggestion`, keyed by `name_key`. Verify with tests for idempotency and case-insensitivity.
- [x] 2.5 Add `accept_suggestion(conn, enrichment_skill_id)` and `accept_all(conn, job_id, enrichment_id, importance)`. Each creates a mark with origin `suggestion`. They refuse when the item is unverified, the run failed, the run is for an older snapshot, or the skill is already marked. Verify with tests for each refusal case and for accept-all skipping skills that are already marked.

## 3. Pipeline core (`enrich/pipeline.py`, `enrich/validate.py`) (D4, D5)

- [x] 3.1 Create `src/jobhunt/enrich/` with `pipeline.py`:
  - the `Segment`, `SkillItem` and `SalaryItem` types
  - the `LLM`, `Segmenter`, `SkillExtractor` and `SalaryExtractor` protocols
  - `StepFailed`, `Cancelled` and `Unreachable`
  - the step registry
  - `pipeline_id()`, which builds the canonical `seg=…@N skills=…@N salary=…@N validate=…@N` text
  
  Add `tests/fakes.py` with `FakeLLM` (scripted responses, recorded requests). Verify with a test that `pipeline_id` is stable and that the registry lists segmenters.
- [x] 3.2 Implement `validate.py`: normalisation (case-fold, whitespace, typographic dashes and quotes), a mapping from normalised to raw offsets, the quote check (source line first, then the whole text), and amount parsing (`175,000`, `175000`, `175k`, 0.5% tolerance). Verify with pure tests, including the two-currency AXIS-style sentence and an invented quote.
- [x] 3.3 Implement `run_pipeline(text, llm, steps, should_stop)`. It returns a `RunResult` with verified and unverified items, the step trace and timings, checks `should_stop` between steps, and stores `StepFailed` as a failure. Verify with tests for success, a failed step and cancellation between steps, all using `FakeLLM`.

## 4. Steps (`segment.py`, `skills.py`, `salary.py`) (D5)

- [x] 4.1 Implement the `rules@1` segmenter: heading patterns, section labelling, and inline "a plus" / "nice to have" switching a line to preferred. Verify with tests on the committed synthetic fixtures and a hand-written description with required and preferred headings.
- [x] 4.2 Implement the `llm-lines@1` segmenter: numbered non-empty lines, a label enum schema, omitted lines treated as `other`, out-of-range numbers ignored, and batching when the token estimate exceeds 60% of `num_ctx`. Verify with `FakeLLM` tests that segments are exact line spans and batching splits a long text.
- [x] 4.3 Implement the `atomic@1` skill extractor: one call per non-empty group, importance taken from the group, and one retry on an empty group with a reminder message, then `StepFailed`. Verify with `FakeLLM` tests: list splitting is passed through, the retry happens once, and two empty results fail with a message naming the group.
- [x] 4.4 Implement the `paylines@1` salary extractor: the pay-line regex, no call when no line matches, and a range-list schema with the `basis` enum. Verify with tests: no request for a posting without pay, and two ranges parsed and verified from the two-currency sentence.

## 5. Ollama client (`enrich/ollama.py`) (D6)

- [x] 5.1 Implement the client with `urllib`:
  - `version`, `models` (from `/api/tags`, with capabilities from `/api/show` cached per digest), `loaded` (`/api/ps`)
  - `chat_json`, which sends `stream: false`, `format`, `keep_alive: "10m"`, temperature 0, seed 7 and `num_ctx`, plus `think: false` only for models with thinking support
  - `Unreachable` on connection errors and `StepFailed` on HTTP or JSON errors
  
  Verify with tests against an `http.server` stub thread that assert the exact request bodies and the error mapping.
- [x] 5.2 Implement `status()` with a 5-second in-process cache. It returns offline, no model, model missing, online, or online with spill (`size_vram < size`). Verify with stub tests for each state and that the cache avoids repeat requests.

## 6. Derived writer and queue (`enrich/derived.py`, `enrich/jobs.py`) (D2, D7)

- [x] 6.1 Implement `derived.save_run(conn, job_id, snapshot_id, model, pipeline, result)`, which writes `posting_enrichments` and the item rows with offsets and verified flags, including failed runs. Verify with engine-fixture tests on both databases: round trip, failed run with error, and that a second run leaves the first unchanged.
- [x] 6.2 Implement `jobs.enqueue` (no duplicate queued or running job per posting; records snapshot, model and pipeline), `enqueue_unextracted(conn, filters)`, `cancel_all`, `recover` and `run_next(engine, llm)`, where `run_next` handles done, failed, cancelled and re-queue on unreachable. Verify with engine-fixture tests for each state change and that `run_next` makes no model calls inside a transaction (FakeLLM asserts no open transaction).
- [x] 6.3 Implement the `Worker` thread: event wait with a 5 s timeout, 10 s back-off while offline, `recover()` at start, and a stop flag. Verify with a test that starts the worker against `FakeLLM`, queues two jobs, and waits until both are done.
- [x] 6.4 Add a re-import test: import, extract (fake), accept one suggestion, reject one, flag labelling complete, then re-import a changed synthetic page. Verify that runs, marks, importance, rejections and the flag are unchanged, and that the old run is reported as made on an older snapshot.

## 7. Read models (`queries.py`)

- [x] 7.1 Add `enrichment_panel(conn, job_id, run_id=None)`: chosen or latest run, list of runs, stale flag, verified and unverified items, already-marked and rejected flags per skill, and the error for failed runs. Verify with engine-fixture tests.
- [x] 7.2 Add a salary summary to `posting_list` rows (first verified range of the latest successful run on the latest snapshot, plus the count of further ranges) and the `labelled` filter in `ListFilters` (URL round trip). Verify with tests on both databases.
- [x] 7.3 Add `unextracted_count(conn, filters, model, pipeline)`, matching `enqueue_unextracted`, and `queue_overview(conn)`. Verify with tests that the count equals the number of jobs that would be queued.

## 8. Web interface (`web/llm.py`, templates, `marks.js`) (D8)

- [x] 8.1 Pass an `ollama` client (or `None`) to `create_app` and register the `llm` blueprint. Add the status badge to `base.html` (`hx-get` on load and every 15 s) with an offline / online / no model / missing / spill fragment. Verify with Flask test-client tests for each state using a fake client.
- [x] 8.2 Add the settings page (`GET`/`POST /settings`): model list filtered to text-generation models, context size, segmenter, Ollama address shown read-only, and an offline message. Verify with web tests: embedding models excluded, values persist, and invalid values give 400.
- [x] 8.3 Add the extract actions:
  - per posting: `POST /postings/<id>/extract`
  - bulk: `POST /extract`, with the count in the button label and `hx-confirm`, disabled while offline or without a model
  
  Add the queue fragment (`GET /llm/queue`, polling every 3 s and returning 286 when idle) and `POST /llm/queue/cancel`. Verify with web tests: deduplication, the count matches, the disabled state, and the 286 response when idle.
- [x] 8.4 Fill the `#model-says` panel: run picker, model, pipeline and time, salary ranges, required and preferred skills with quotes, `<details>` for unverified items, stale label with re-extract, failed-run error, and Accept / Accept all / Reject / Undo, with htmx fragment swaps. Verify with web tests, including literal rendering of `<b>Go</b>` and that accept is refused on a stale run.
- [x] 8.5 Show the derived salary summary in `postings/_rows.html`, styled `.src-derived`, with "+N more". Verify with a web test on the list.
- [x] 8.6 Add importance to the mark popup in `marks.js` and the form, an importance select per mark in `triage/_marks.html`, the "labelling complete" toggle, and the `labelled` filter control on the list. Verify with web tests for the new POST routes. The `marks.js` change is checked by hand in a browser, as before.
- [x] 8.7 Add guard tests: each new POST route rejects a cross-origin request with 403, and each GET route leaves the database unchanged.

## 9. CLI (`cli.py`)

- [x] 9.1 Add `--ollama-url` (default `$JOBHUNT_OLLAMA_URL` or `http://localhost:11434`) to `serve`. Print it at startup. Start the `Worker` after `create_app`, but not in the debug reloader's parent (`WERKZEUG_RUN_MAIN`). Verify with `test_cli_serve.py` tests for the default, the environment override, and that the worker starts once with `--debug` simulated.
- [x] 9.2 Implement `enrich/evaluate.py`:
  - `labelled_set` with blind and reviewed groups
  - run reuse or fresh runs
  - key-then-overlap matching, each item matched at most once, with rejections counted as unmatched
  - segment recall and miss attribution (segmenter, extractor, unlocated) from the run's stored segments
  - metrics and the text and JSON report
  
  Verify with engine-fixture tests for matching (the "PyTorch framework" scenario), recall 4/5, the grouping, and attribution: an unmatched mark outside every required or preferred segment counts as a segmenter miss, one inside such a segment as an extractor miss, and one whose quote is gone from the latest snapshot as unlocated and outside segment recall.
- [x] 9.3 Add `jobhunt eval [--model] [--segmenter] [--fresh] [--json] [--db] [--ollama-url]`. When there is no labelled set, it prints guidance and exits 1. When Ollama is unreachable and runs are needed, it exits 1 and writes nothing. Verify with CLI tests using a fake client and the stub server.

## 10. Documentation and final checks

- [x] 10.1 Update CLAUDE.md:
  - project status
  - the `enrich/` architecture
  - four data kinds and their writers
  - the Ollama address, settings and worker behaviour
  - the `serve --ollama-url` and `eval` commands
  - labelling workflow: label 5–10 postings blind, flag them complete, then extract
  - the backup note for `0003`
  
  Verify by reading it against the final code.
- [x] 10.2 Run `pytest` on SQLite and with `JOBHUNT_TEST_PG_URL` on Postgres; all pass. Run `openspec validate add-ollama-enrichment --strict`; it passes.
- [x] 10.3 Manual check with the user's Ollama running:
  - the badge shows the model
  - extract one posting from the UI and see the panel fill
  - accept and reject a suggestion
  - stop Ollama and confirm the badge goes offline and the app keeps working
  
  Run the extraction only with the user's go-ahead, since it uses their GPU.
