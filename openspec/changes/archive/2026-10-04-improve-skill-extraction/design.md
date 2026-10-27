## Context

The motivation comes from the first eval run; see proposal.md, "Why". The relevant current state:

- **Segmenter.** `llm-lines@1` sends numbered lines and receives a label per line. Its system prompt lists "duties" under `other`. `rules@1` starts a required section only at qualification-style headings.
- **Extractor.** `atomic@1` makes one call per non-empty group (required, preferred). Importance comes from the group, never from the model. The prompt asks for skills the lines "ask for", and `kind` is one of technical, domain or soft.
- **Pipeline.** `run_pipeline` runs segment → skills → salary, then `validate.check_skills` / `check_salaries`. It records the checked items in `trace["items"]`. `derived.save_run` stores one `enrichment_skills` row per checked item, keyed by `userdata.name_key(name)`.
- **Eval.** `evaluate.py` places a mark with `validate.locate`, which takes the first normalised substring match. It splits postings into blind/reviewed by whether any mark has origin `suggestion`. Precision counts every unmatched suggestion as wrong.
- **Rejections and accepts.** Rejected suggestions are stored per posting and skill key, and apply to every run. Accepted suggestions become marks with origin `suggestion`.
- **`kind`.** It is written to `enrichment_skills.kind` (free text) and is read nowhere else.

## Goals / Non-Goals

**Goals:**
- Make the pipeline's definition of a skill match the user's: duties included, traits, fragments and industries excluded, advanced degrees named by level.
- One suggestion per skill per run, at the higher importance.
- An eval whose numbers mean what they say: no substring mis-placement, recall measured only against labels the user made unaided, and precision measured only where the user has judged.

**Non-Goals:**
- Mapping skill names to a canonical skill (aliases, embeddings). The merge here uses exact `name_key` equality only.
- Changing how the validator verifies quotes.
- Any schema migration, or changing how marks are stored (no offsets on marks).
- Running models. The final task needs the user's go-ahead before using the GPU.

## Decisions

### D1. Duties are labelled `required`; no separate `duty` label

Both segmenters put duty lines into the existing `required` label. With "higher importance wins" (D5), a skill named in a duty and also in a "nice to have" line comes out required either way, so a separate label would add schema, UI and eval surface without changing any result.

*Alternative considered:* a fourth label `duty` mapped to required at extraction. It would let the analysis weigh duty skills separately later. Rejected for now; it can be added as a new segmenter version if the analysis needs it.

### D2. `llm-lines@2`: new label definitions in the prompt

The prompt's label definitions become:

- `required`: a skill, qualification or experience the candidate must have, **or work the hire will do** (duty bullets, and sentences describing the role's work)
- `preferred`: as before
- `other`: the company, team, product, mission, benefits, pay, headings, legal text

The JSON schema, batching and "you may leave out other lines" stay the same, so `FakeLLM` scripts keep their shape.

### D3. `rules@2`: duty headings start a required section

`_REQUIRED_HEADING` gains duty headings: `responsibilit`, `duties`, `what you['’]ll do`, `what you will do`, `in this role`, `your role`, `day[- ]to[- ]day`, `accountabilit`. The `is_heading` rules are unchanged; the five-words-or-fewer section-name rule picks up "Key Responsibilities". "About the role" is deliberately left out: in the saved postings it often introduces the company as much as the work. The inline "a plus" rule still makes a line in a required section preferred.

### D4. `atomic@2`: what counts as a skill goes in the prompt, not a filter on `kind`

The system prompt gains:
- **Scope:** skills the lines ask for, or that the work they describe uses.
- **Include:** technologies, tools, platforms, languages and methods; soft skills that name a capability (communication, stakeholder management, technical leadership); calls for an advanced degree.
- **Exclude:** personality traits (adaptability, independence, comfort with ambiguity); industries and subject domains (fintech, insurance, genomics); fields of study; words that name no skill on their own ("trends", "systems").
- **Degree naming:** `PhD`, `Master's degree` or `Advanced degree`; the lowest level that qualifies; the field stays in the quote.
- **Kinds:** `kind` enum `technical | soft | qualification`, with one line defining each.

`EMPTY_REMINDER` changes from "they ask for at least one skill" to say the lines ask for or describe work that uses at least one skill.

*Why not filter on `kind`:* in the eval runs the model used `domain` as a catch-all. It covered fintech and insurance, but also refactoring, prompt engineering, hypothesis testing and coding agents: 98 unmatched suggestions against 22 matched. Dropping `domain` would discard real methods.

*Why not give the model the user's existing skill names:* those names come from labelling the eval postings, so the eval would partly score the labels fed back to the model. Normalising names belongs to the grouping change.

`pipeline.SKILL_KINDS` becomes `("technical", "soft", "qualification")`. Stored rows keep `domain`; nothing reads `kind`, so no migration or display change is needed.

### D5. Higher importance wins: merged in the validator (`v@2`), after verification

A new `validate.merge_skills(checked)` runs in `run_pipeline` right after `check_skills`. Among *verified* items with equal `name_key(name)`, it keeps the first item at the highest importance (`IMPORTANCES` order: required, preferred) and drops the rest. Unverified items pass through untouched. `trace["items"]["skills"]` keeps every checked item, so the dropped duplicates stay visible in the run's trace. They are not stored as `enrichment_skills` rows. `validate.VERSION` becomes 2.

*Why after verification:* if the merge ran first, a required item with an invented quote could knock out a verified preferred one, and the skill would vanish from the suggestions.

*Why in the pipeline, not at read time:* every reader would otherwise need to dedupe: the panel, accept-all, the eval, and the later analysis. A run's stored rows then mean "the suggestions", and the pipeline id records that the rule applied.

`validate.py` imports `name_key` from `userdata`, as `derived.py` already does. It stays free of HTTP and database code.

### D6. Eval places marks by whole word, at every occurrence (eval only)

`evaluate.placements(text, quote) -> list[tuple[int, int]]` normalises with `validate.normalise` and finds every occurrence. It keeps the whole-word ones, checking only the edges where the quote itself starts or ends with a letter or digit (so `C#`, `C++` and `.NET` work). It falls back to all occurrences when none are whole-word, so partial-word selections such as "Claude Cod" still place.

`match` overlaps a suggestion span against any placement. `score` counts a mark as reached when any placement overlaps a required or preferred segment.

*Why not change `validate.locate`:* it verifies the model's quotes, and making it stricter would change verification (another validator version) for no measured gain. *Why not store offsets on marks:* the 107 existing marks would still need this, and it needs a migration and a `marks.js` change. Offsets can come later if this proves insufficient.

### D7. Scoring by mark origin replaces blind/reviewed

- `Labelled.group` and `GROUPS` go. The report has one set of counts.
- `match` orders free marks selected-first, so a suggestion that could pair with either pairs with a selected mark and counts toward recall.
- Per suggestion (bucketed by the suggestion's importance):
  - **right:** it matches any mark
  - **wrong:** it is rejected; rejected suggestions still never match
  - **unjudged:** anything else

  Precision is right / (right + wrong), and unjudged is reported beside it.
- Recall, importance agreement, segment recall and miss attribution use selected marks only. Accepted marks copy a suggestion's importance, so including them would make agreement trivially high.
- Text report: one block, with a precision line like `precision 85% (57/67), 124 unjudged`. JSON: the `groups` object is replaced by top-level `postings`, `failures`, `precision`, `unjudged`, `recall`, and so on, with counts kept so a strict floor (unjudged counted as wrong) can be computed from the JSON.

*Alternative considered:* keep blind/reviewed and add judged precision. Rejected because one acceptance still moves the whole posting out of the blind group, so the user can't fix incomplete labels without losing recall data.

### D8. Labelling conventions (documented, not enforced)

In CLAUDE.md:
- Marks follow the same rules as the pipeline: higher importance wins, and duties count as required.
- A skill the user learned about from a suggestion should be **accepted, not selected by hand**. A hand-selected mark counts toward recall, and selecting after seeing the model's output would flatter it. The eval can't detect this.

## Risks / Trade-offs

- **More suggestions to review.** Duty lines bring more incidental vocabulary, so the unjudged count will rise. → Rejections persist by skill key across runs, so review effort goes down with each run; the exclusion rules target the noisiest categories.
- **A 12B model may not follow the include/exclude lists.** → The eval's unjudged and wrong suggestions show which categories leak. Prompt wording can iterate under `atomic@3`.
- **Degree names vary** (`Ph.D.`, `Doctorate`). → Merge and match use exact `name_key`; variants stay separate until the grouping change. The eval shows how often this happens.
- **A required group made only of prose duty lines may yield no skills**, which fails the run after one retry. → The eval reports failed runs; if it happens, relax the retry rule in a later extractor version rather than storing empty results.
- **Higher-wins hides a "preferred" signal.** A skill named in duties but a "plus" in qualifications reads as required. → This is the user's chosen rule. The trace keeps both items.
- **Recall shrinks to what the user found unaided.** A skill only ever accepted counts for no model's recall. → Intended: recall measures finding what the user would mark; precision covers the rest.
- **Hand-selecting after seeing suggestions inflates recall.** → The convention in D8; this can't be enforced.
- **All existing runs become a different pipeline.** → Re-running the 9 labelled postings takes about 5 minutes on the user's GPU. That needs the user's go-ahead (final task). Old runs stay viewable.

## Migration Plan

- No schema change. The pipeline id becomes `seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@2`.
- Jobs still queued under an `@1` pipeline fail with "not available in this version" (existing behaviour); the user re-queues them.
- Rollback: revert the code. Stored `@2` runs stay viewable. `@2` jobs left queued fail the same way.
