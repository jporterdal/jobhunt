## 0. Prerequisites

- [x] 0.1 Confirm that `tighten-skill-definition` is applied and archived: `skill_extractors()` has the keys `atomic@2` and `atomic@4`, and `DEFAULT_SKILLS == "atomic@2"`. Verify before editing; if not, stop and tell the user.
- [x] 0.2 Record the figures before changing any code: `jobhunt eval --json --ollama-url http://127.0.0.1:9` (a closed port, so no model runs). Verify that it reports 0 new runs, and save its recall, wrong and unjudged counts for 7.3.

## 1. Schema (D4, D5)

- [x] 1.1 Add `posting_triage.skills_first_complete_at` and `rejected_suggestions.reason` to `db.py`, and generate migration `0004_feedback` against a scratch database at head (CLAUDE.md, "Schema migrations"). Fill `skills_first_complete_at` from `skills_complete_at` in `upgrade()`, and drop both columns in `downgrade()`. Verify with `pytest tests/test_migrate.py` on SQLite and Postgres, and an upgrade-then-downgrade on a copy of `data/jobhunt.db` that keeps every labelled posting's first-complete time.

## 2. User data (D1, D4, D5)

- [x] 2.1 `userdata`: `llm.skills` in `DEFAULT_SETTINGS` (`"atomic@2"`), validated against `skill_extractors()` in `set_setting`; `eval.holdout_start` (a UTC time or empty), validated. Verify with userdata tests: the default, choosing `atomic@4`, refusing `atomic@3` with the available names, setting and clearing the start.
- [x] 2.2 `set_skills_complete` sets `skills_first_complete_at` when it is empty and the flag is set, and never clears it. Verify with a test: flag, clear, flag again keeps the first time.
- [x] 2.3 `reject_suggestion` takes a required reason (`not-a-skill` or `not-for-me`); add `set_rejection_reason`, which refuses unknown values and rows that don't exist. Verify with userdata tests on SQLite and Postgres, including that an old NULL-reason row can be given a reason and stays rejected.

## 3. Pipeline and jobs (D1)

- [x] 3.1 `steps_for(segmenter, skills)`; `jobs.current_pipeline` passes the `llm.skills` setting, falling back to `DEFAULT_SKILLS` when the stored method isn't registered. Verify with a jobs test: with `atomic@4` chosen, a requested extraction stores a run whose pipeline id contains `skills=atomic@4` and whose request has the `atomic@4` prompt; with an unknown stored value, it uses `atomic@2`.

## 4. Web (D1, D4, D5)

- [x] 4.1 Settings page: the skill method select (registry order, the stored value marked unavailable when unknown); the held-out start with set and clear actions, and the development and held-out posting counts. Verify with web tests (Flask test client, `FakeOllama`): the choices, persistence, refusal of an unknown method, set and clear of the start.
- [x] 4.2 Suggestion panel: two reject actions ("Not a skill", "Not for me") in place of one; shown rejected suggestions show their reason or "no reason", with actions to set it. Keep GET handlers read-only. Verify with web tests: each action stores its reason, setting a reason on a NULL row, rendering of all three states, and the Origin check on the new POST route.

## 5. Evaluation (D2, D3, D5, D6)

- [x] 5.1 Per-posting scoring: `score` fills one `Counts` per posting, `Counts` adds, and the report sums postings into sets. Verify that the existing eval tests pass unchanged.
- [x] 5.2 `rejected_keys` returns key → reason; the report counts wrong suggestions per reason (not a skill, not for me, no reason) for each set. Verify with an eval test matching the spec scenario "Wrong suggestions by reason".
- [x] 5.3 Development and held-out sets from `eval.holdout_start` and `skills_first_complete_at`, each with its posting count; one set when no start is stored. Verify with eval tests matching "Labelled after the start", "No held-out set" and "Re-flagging keeps a posting in development".
- [x] 5.4 The count of selected marks created after their posting's first succeeded run, per set. Verify with an eval test matching "Mark selected after a run".
- [x] 5.5 `evaluate(..., skills=...)`; per-posting JSON detail (missed, wrong with reason, unjudged). Verify with a JSON test that checks the detail lists and that the single-method top-level fields are unchanged.

## 6. Command (D2)

- [x] 6.1 `jobhunt eval --skills A[,B...]`: validate every method first (unknown → exit 1 naming the available ones, no requests); plan and print the new runs per method; refuse to run any when Ollama is unreachable and runs are needed; one method prints as today plus the new lines; several print the side-by-side table and the mark differences, and JSON as `{"methods": [...], "differences": [...]}`. Verify with CLI tests (`FakeLLM`, stdlib stub) for "Unknown skill method", "Comparing stored runs" (no requests made) and "Marks found by one method only".

## 7. Docs, full run and real-data check

- [x] 7.1 CLAUDE.md: the skill method in "Settings page", the `eval` options in "Commands" (`--skills`), the sets, reasons and warning in "Labelling and eval" (reject with a reason; start a held-out set before labelling new postings), migration `0004` in "Data and backups" if it drops data on downgrade, and the project status. Verify with `grep -n "skills\|held-out\|not for me" CLAUDE.md`.
- [x] 7.2 Run `pytest`, and the Postgres run if available, then `openspec validate accumulate-extraction-feedback --strict`. Verify that all pass.
- [x] 7.3 Copy `data/jobhunt.db`, then (no model runs) run `jobhunt eval --ollama-url http://127.0.0.1:9` and `jobhunt eval --skills atomic@2,atomic@4 --ollama-url http://127.0.0.1:9`. Verify that the first matches the figures saved in 0.2, and that the comparison reuses all 18 stored runs and shows 91/102 and 77/102 recall with the marks only one method found (or the re-scored figures if labels changed, reported to the user). Report the "selected after a run" count to the user.
