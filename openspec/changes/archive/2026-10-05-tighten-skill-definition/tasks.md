## 0. Prerequisites

- [x] 0.1 Confirm that `locate-quotes-on-whole-words` is implemented (`validate.VERSION == 3`). Verify before editing; if it isn't, stop and tell the user.
- [x] 0.2 Record the baseline before changing any code. Run `jobhunt eval --json --ollama-url http://127.0.0.1:9` (a closed port, so it can't run a model) on the current labels and judgments. It reuses the stored `atomic@2`/`v@3` runs. Verify that it reports `0` new runs and save its recall and wrong count (recorded 2026-10-05: recall 91/102, 103 wrong of 311 judged). If it exits because runs are missing, stop and tell the user: the measurement step of `locate-quotes-on-whole-words` hasn't been run.

## 1. Prompt (`enrich/skills.py`) (D1–D4, D6)

- [x] 1.1 Rewrite the opening of `SKILLS_SYSTEM` so that the lines must *name* the skill (D1). Add the bar and the exclusion list (D2) after the existing exclusions, which stay word for word. Replace the soft-skill examples and add the ability rule (D3). Verify with `grep -n "stakeholder\|leadership\|work they describe" src/jobhunt/enrich/skills.py`, which should find nothing.
- [x] 1.2 Reword `EMPTY_REMINDER` (D4) and bump `AtomicExtractor.version` to 3. Verify that `test_empty_group_retried_once` and `test_two_empty_results_fail` pass unchanged.
- [x] 1.3 Check every example word in the new prompt against the user's mark names (read-only query on `data/jobhunt.db` over skills joined to marks). Verify that no example matches a mark name by `name_key`, and report any match to the user rather than keeping it.

## 2. Tests and pipeline id

- [x] 2.1 Update `test_prompt_names_kinds_and_degree_levels`: drop the "work they describe" assertion, and assert that the system prompt contains the D2 category phrases ("activities the job involves", "basics", "team practices", "kinds of data", "before a colon") and does not contain "stakeholder management". Verify with `pytest tests/test_enrich_pipeline.py`.
- [x] 2.2 Update the pipeline-id strings to `skills=atomic@3` in `tests/conftest.py` and `tests/test_enrich_pipeline.py`, and the comment in `src/jobhunt/db.py`. Verify with `grep -rn "atomic@2" src tests`, which should find nothing except intentional history.

## 3. Docs and full test run

- [x] 3.1 Update CLAUDE.md: the pipeline id in "Model enrichment", and add the skill bar to "Labelling and eval" (label only expertise worth screening for, named in the text; not activities, basics or team practices). Verify with `grep -n "atomic@" CLAUDE.md`.
- [x] 3.2 Run `pytest`, and the Postgres run if available. Then run `openspec validate tighten-skill-definition --strict`. Verify that all pass.

## 4. Measure `atomic@3` (needs the user's go-ahead before any GPU use)

- [x] 4.1 Ask the user to approve 9 model runs (about 30 s each) on their GPU. Verify by explicit user confirmation in the conversation; do not proceed without it.
- [x] 4.2 Copy `data/jobhunt.db`, then run `jobhunt eval --json` and record the figures next to the 0.2 baseline in design.md ("Measurement of `atomic@3`"). (Failed the recall criterion: 76/102, 24 wrong, 0 failures; revised in section 5.)
- [x] 4.3 For the new run, list the remaining wrong suggestions by the categories in proposal.md, the newly missed marks, and the unjudged suggestions. Read the new suggestions on posting A, posting D, posting E and posting F against the spec scenarios. Verify by delivering that summary to the user, who then reviews the unjudged suggestions in the UI.

## 5. Revise to `atomic@4` (D6–D9)

- [x] 5.1 Edit `SKILLS_SYSTEM`: add the practice and discipline lines after "Do not work out skills…" (D7), narrow "fields of study" and the activities exclusion (D7), and add the leave-out-only-the-words line after the D2 list (D8). Bump `AtomicExtractor.version` to 4. Verify with `grep -n "everyday activities\|named as part of a degree\|Leave out only the excluded words" src/jobhunt/enrich/skills.py`, which should find all three.
- [x] 5.2 Check the new examples (Experiment design, Performance tuning, Site reliability engineering, Physics, Kubernetes) against the user's mark names (read-only, by `name_key`). Verify that none matches (D9), and report any match to the user rather than keeping it.
- [x] 5.3 Update `test_prompt_names_kinds_and_degree_levels` to assert "everyday activities", "named as part of a degree" and "Leave out only the excluded words" (replacing "activities the job involves"), and the pipeline-id strings to `skills=atomic@4` in `tests/conftest.py`, `tests/test_enrich_pipeline.py` and the comment in `src/jobhunt/db.py`. Verify with `pytest tests/test_enrich_pipeline.py` and `grep -rn "atomic@3" src tests --include=*.py`, which should find nothing.
- [x] 5.4 Update the pipeline id in CLAUDE.md ("Model enrichment") and the change's note in "Project status" to `atomic@4`. Verify with `grep -n "atomic@" CLAUDE.md`.
- [x] 5.5 Run `pytest`, and the Postgres run if available. Then run `openspec validate tighten-skill-definition --strict`. Verify that all pass.

## 6. Measure `atomic@4` (needs the user's go-ahead before any GPU use)

- [x] 6.1 Ask the user to approve 9 model runs (about 30 s each) on their GPU. Verify by explicit user confirmation in the conversation; do not proceed without it.
- [x] 6.2 Copy `data/jobhunt.db`, then run `jobhunt eval --json`. Compare with the success criteria in proposal.md against the `atomic@2` baseline from 0.2 (at most 51 wrong, recall at least 88/102, 0 failures), and report each figure next to the baseline and the `atomic@3` figures. If labels or judgments changed after 0.2, re-score the stored `atomic@2` runs (no model calls) and ask the user how to re-baseline. (Baseline re-scored unchanged. Failed the recall criterion: 77/102, 28 wrong, 0 failures; the user chose to keep `atomic@2` as the default, section 7.)
- [x] 6.3 For the new run, list the remaining wrong suggestions by category, the marks missed compared with the baseline, and the unjudged suggestions. Read the new suggestions on posting A, posting D, posting E, posting F and posting G against the spec scenarios. Verify by delivering that summary to the user, who then reviews the unjudged suggestions in the UI.

## 7. Close out: `atomic@2` default, `atomic@4` beside it (D10–D11)

- [x] 7.1 In `enrich/skills.py`, give `AtomicExtractor` its version, prompt and retry text per instance. Restore the `atomic@2` prompt and retry text word for word from commit `128f5a3` as `SKILLS_SYSTEM_V2`/`EMPTY_REMINDER_V2`, keep the current ones as the `atomic@4` texts, and set `EXTRACTORS` to the two instances. Verify that the `atomic@2` texts match `git show 128f5a3:src/jobhunt/enrich/skills.py` exactly (compare the strings in Python).
- [x] 7.2 In `enrich/pipeline.py`, key `skill_extractors()` by `name@version`, set `DEFAULT_SKILLS = "atomic@2"`, and make `steps_from_id` look the skill step up by its full `name@version`. Verify that `steps_from_id` resolves both `skills=atomic@2` and `skills=atomic@4` ids, and raises for `skills=atomic@3`.
- [x] 7.3 Tests: pipeline-id strings back to `skills=atomic@2` in `tests/conftest.py` and `tests/test_enrich_pipeline.py`, and the `src/jobhunt/db.py` comment; the existing prompt-phrase test runs against the `atomic@4` instance; add tests that the default request is the `atomic@2` text (no "everyday activities", still "work they describe"), that both ids resolve and `atomic@3` doesn't, and that a queued job naming `atomic@4` runs with the `atomic@4` request. Verify with `pytest tests/test_enrich_pipeline.py tests/test_jobs.py`.
- [x] 7.4 Update CLAUDE.md: the default pipeline id back to `atomic@2`; in "Model enrichment", that skill extractors are registered by name and version and `atomic@4` is kept beside the default, with choosing it left to `accumulate-extraction-feedback`; the project status sentence for this change (stricter prompts measured, not adopted; kept as `atomic@4`); "Label by the pipeline's rules" becomes the user's bar, since the default prompt is broader than it. Verify with `grep -n "atomic@" CLAUDE.md`.
- [x] 7.5 Run `pytest`, and the Postgres run if available, then `openspec validate tighten-skill-definition --strict`. Then run `jobhunt eval --ollama-url http://127.0.0.1:9` (a closed port, so no model runs). Verify that all tests pass, the change is valid, and the eval reports `0 new, 9 reused` with recall 91/102 and 103 wrong of 311 (or the re-scored figures if labels changed, reported to the user).
