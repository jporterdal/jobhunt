## Why

The first `jobhunt eval` over 9 blind-labelled postings (`gemma4:12b`, `seg=llm-lines@1 skills=atomic@1 salary=paylines@1 validate=v@1`) reported 78% recall and 29% precision. Looking at each miss and false positive showed that most of the gap is a disagreement about what counts as a skill, plus measurement error, rather than model failure:

- 18 of 24 missed skills were on duty lines ("Lead the supervised fine-tuning work"), which the segmenter is told to label `other`. The user counts skills named in duties as required.
- Most of the 205 unmatched suggestions are real tools the user skipped when labelling, or things the user does not want: industries (fintech, insurance), degree fields (physics), personality traits (adaptability), sentence fragments ("trends", "controls") and same-skill duplicates.
- The eval places a mark at the first substring match of its quote, so `Git` lands in "di**git**al" and `CI` in "de**ci**sion", which mis-attributes misses and breaks overlap matching.
- Precision treats every suggestion the user did not mark as wrong, and accepting one suggestion moves a whole posting from "blind" to "reviewed". So there is no way to say "the model was right, I missed it" without spoiling the posting for recall.

The definitions need to be settled before comparing models or prompts.

## What Changes

- **Duties count as required.** Lines describing the hire's work (duty bullets and prose about the role) are segmented as `required`. Lines about the company, team, product, benefits, pay and legal text stay `other`. Segmenters bump to `llm-lines@2` and `rules@2` (duty headings start a required section).
- **What counts as a skill.** The extractor keeps tools, technologies, methods and soft skills that name a capability (communication, stakeholder management). It drops personality traits, fragments, industries and domains, and degree fields. A call for an advanced degree is kept, named by level: `PhD`, `Master's degree` or `Advanced degree`, using the lowest level that qualifies. The extractor also takes skills from duty lines, not only from lines that ask for something. Extractor bumps to `atomic@2`.
- **Skill kinds** become `technical`, `soft` and `qualification` (was `technical`, `domain`, `soft`). This applies to new runs only. Stored runs keep `domain`.
- **Higher importance wins.** When a run's verified suggestions include the same skill more than once, only one is kept, at the highest importance (required beats preferred). This also removes same-importance duplicates. Validator bumps to `v@2`.
- **Eval places marks by whole word, at every occurrence.** The eval locates each mark's quote where it is not part of a longer word, falling back to plain substring matches only when there is none, and considers every occurrence when matching and attributing misses. The validator's own quote check is unchanged.
- **BREAKING (eval report): scoring by mark origin replaces blind/reviewed groups.**
  - Recall counts only marks the user selected themselves.
  - Precision counts a suggestion as right when it matches any mark (selected or accepted) and as wrong when the user rejected it. A suggestion that is neither is *unjudged*: it is left out of precision and its count is reported.
  - The text and JSON reports lose the per-group sections.

Out of scope:
- Grouping skill names (`Azure` = `Microsoft Azure`). Planned as its own change.
- Correcting the user's existing labels (importance, duplicate and combined marks).
- Running the new pipeline against the user's GPU, which needs the user's go-ahead.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `posting-enrichment`: segment labels now cover duties. Skill extraction defines what counts as a skill, how advanced degrees are named, the new kinds, and the rule that the higher importance wins among duplicates.
- `enrichment-evaluation`: the labelled set has no blind/reviewed groups; the report scores by mark origin, with unjudged suggestions; matching and miss attribution use whole-word, every-occurrence placement.

## Impact

- **Code.** `src/jobhunt/enrich/segment.py` (both segmenters), `skills.py` (prompt, schema enum, empty-group reminder), `pipeline.py` (`SKILL_KINDS`, applying the merge after validation), `validate.py` (merge, version), `evaluate.py` (labelled set, mark placement, scoring, report), `cli.py` only if report wiring changes.
- **Schema.** No migration. `enrichment_skills.kind` is free text, and old rows keep `domain`.
- **Stored runs.** Every pipeline id changes, so the eval and the posting list's "already extracted" check treat old runs as a different pipeline. Old runs stay viewable. Jobs still queued under an `@1` pipeline fail with "not available in this version", which is existing behaviour.
- **Tests.** Pipeline-id strings in `tests/conftest.py`, `test_enrich_pipeline.py`, `test_web_llm.py`, `test_cli_eval.py`, `test_evaluate.py`; blind/reviewed tests in `test_evaluate.py` and `test_cli_eval.py`; `FakeLLM` scripts for the new prompts.
- **Docs.** CLAUDE.md: pipeline id, the eval description ("blind"/"reviewed"), and the labelling advice (accept a suggestion rather than selecting the same skill by hand).
