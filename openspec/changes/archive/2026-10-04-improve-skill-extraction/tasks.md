## 1. Segmenters (`enrich/segment.py`) (D1, D2, D3)

- [x] 1.1 `llm-lines@2`: rewrite `LINES_SYSTEM` so `required` covers work the hire will do (duty bullets and sentences about the role's work), and `other` lists the company, team, product, mission, benefits, pay, headings and legal text. Bump `LineClassifier.version` to 2 and the section comment. Verify with a `FakeLLM` test that the system prompt sent mentions duties under required, and that the existing segment-span and batching tests still pass.
- [x] 1.2 `rules@2`: add the duty headings from D3 to `_REQUIRED_HEADING`, bump `RuleSegmenter.version` to 2 and the section comment. Verify with tests: lines under "Key Responsibilities" and "What you'll do:" are required; a "… is a plus" line under "Responsibilities" is preferred; lines under "About the role" stay other; the existing synthetic-fixture tests still pass, with updated expectations where a fixture has a duty section.

## 2. Skill extractor (`enrich/skills.py`, `enrich/pipeline.py`) (D4)

- [x] 2.1 Change `pipeline.SKILL_KINDS` to `("technical", "soft", "qualification")`. Update `tests/test_suggestions.py` and any other test building a `SkillItem` with kind `domain`. Verify with `pytest -k "suggestion or pipeline"`.
- [x] 2.2 `atomic@2`: rewrite `SKILLS_SYSTEM` with the scope, include and exclude lists, degree naming and kind definitions from D4. Reword `EMPTY_REMINDER` for duty lines. Bump `AtomicExtractor.version` to 2. Verify with a `FakeLLM` test that the prompt sent names the three kinds and the degree levels, and that a `qualification` item passes `conform`, while an item with kind `domain` is rejected by the schema check.

## 3. Higher importance wins (`enrich/validate.py`, `enrich/pipeline.py`) (D5)

- [x] 3.1 Add `validate.merge_skills(checked)`: among verified items with equal `name_key(name)`, keep the first at the highest importance; pass unverified items through in order. Bump `validate.VERSION` to 2. Verify with pure tests covering:
  - a required and a preferred duplicate → one required item
  - two required duplicates → the first is kept
  - a verified preferred item with an unverified required twin → both kept
  - name variants differing only in case or spacing are merged
- [x] 3.2 Call `merge_skills` in `run_pipeline` after `check_skills`. `trace["items"]["skills"]` keeps the full checked list; `RunResult.skills` holds the merged list. Verify with a `run_pipeline` test where `FakeLLM` returns the same skill from both groups: one stored suggestion, at required, and two entries in the trace.
- [x] 3.3 Update every pipeline-id string to `seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@2` (and `seg=rules@2` where used): `tests/conftest.py`, `test_enrich_pipeline.py`, `test_web_llm.py`, `test_cli_eval.py`, `test_evaluate.py`, and the comment in `db.py`. Keep `test_jobs.py`'s `seg=gone@1` case. Verify with `pytest`.

## 4. Eval: mark placement (`enrich/evaluate.py`) (D6)

- [x] 4.1 Add `placements(text, quote)`: every whole-word occurrence in normalised text mapped to raw offsets, with a fallback to all occurrences when none are whole-word. Verify with pure tests:
  - `Git` in "digital … Git" → only the second
  - `C#`, `C++` and `.NET` found next to punctuation
  - `Python` twice → both
  - a partial selection `Claude Cod` → found by the fallback
  - an absent quote → empty list
- [x] 4.2 Use placements in `match` (overlap with any placement) and `score` (reached when any placement overlaps a required or preferred segment; not located when there are no placements). Verify with tests for the spec scenarios "Quote inside a longer word" and "Reached at a later occurrence".

## 5. Eval: scoring by origin (`enrich/evaluate.py`, `cli.py`) (D7)

- [x] 5.1 Remove `GROUPS` and `Labelled.group`. Order free marks selected-first in `match`. In `Counts`, track right, wrong and unjudged suggestions per importance bucket. Recall, importance agreement, segment recall and misses count selected marks only. Verify with tests for the spec scenarios "Selected and accepted marks on one posting", "Accepted suggestion" and "Rejected and unjudged suggestions", plus a suggestion overlapping both a selected and an accepted mark pairing with the selected one.
- [x] 5.2 Rework `Report.to_dict` and `format_text` into one block with precision as `NN% (right/right+wrong), N unjudged`; JSON gets top-level counts in place of `groups`. Update `tests/test_cli_eval.py` and `tests/test_evaluate.py` (remove the blind/reviewed tests). Verify with `pytest tests/test_evaluate.py tests/test_cli_eval.py` and by running `jobhunt eval --json` against a copy of the database holding only stored `@1` runs: it needs new runs and, with Ollama stopped or `--ollama-url` pointed at a closed port, exits non-zero without writing.

## 6. Docs and full test run

- [x] 6.1 Update CLAUDE.md:
  - the pipeline id in "Model enrichment"
  - "Labelling and eval": no blind/reviewed groups; scoring by origin; the conventions from D8 (marks follow higher-wins and duties-as-required; accept a skill learned from a suggestion rather than selecting it by hand)
  - the `evaluate.py` line in "Architecture"
  
  Verify that `grep -n "blind\|reviewed\|@1" CLAUDE.md` shows only intended mentions.
- [x] 6.2 Run `pytest`, and `JOBHUNT_TEST_PG_URL=postgresql+psycopg:///jobhunt_test pytest` if Postgres is available. Verify that both pass. Then run `openspec validate improve-skill-extraction`.

## 7. Measure (needs the user's go-ahead before any GPU use)

- [x] 7.1 Ask the user to confirm that their label corrections are done (importance per higher-wins, duplicate and combined marks split or removed, `CALM` renamed, `Claude Cod` fixed), and to approve about 9 model runs on their GPU. Verify by explicit user confirmation in the conversation; do not proceed without it.
- [x] 7.2 Copy `data/jobhunt.db`, then run `jobhunt eval` (new pipeline id, so new runs are made automatically). Verify that the report shows 9 new runs and 0 failures, or report the failures with their errors.
- [x] 7.3 Compare with the baseline (`@1`: recall 78% (83/107), precision 29% (83/288), 18 segmentation, 6 extraction misses). Summarise for the user which misses remain and which suggestion categories still leak. Verify by delivering that summary; the user then reviews unjudged suggestions in the UI and re-runs `jobhunt eval` without GPU use.
