## Why

The user reviewed the `atomic@2` suggestions on 9 labelled postings and rejected 99 of 286, so precision is 65%. Sorted by hand, the rejections are mostly not model errors. They are things the prompt's definition of a skill lets through:

| Category | Rejected | Examples |
|---|---|---|
| Activities the job involves | 25 | Refactoring, Debugging, Code reviews, On-call rotation, KPI definition, Rollback |
| Basics and team practices | 23 | YAML, Unit testing, A/B tests, Agile SCRUM, SOLID principles, Design patterns, Quantization |
| Inferred from intro paragraphs | 12 | Code quality, Test coverage, Troubleshooting, Simulation, AI models |
| Soft-skill padding | 11 | Stakeholder management ×5, Collaboration, Reasoning, Presentation skills |
| Vague terms | 11 | AI technologies, AI tools, Coding, Architecture, Implementation |
| Kinds of data or records | 9 | EHRs, claims, imaging, registries, clinical records |
| Kinds of past job, bullet labels | 8 | Professional services, Solutions engineering, Evals (a bullet label) |

The user's test for a skill is narrower than the prompt's: expertise a hiring team would screen for, which takes real study or practice to gain. Something nearly every CS graduate has, something learnable in minutes, or a team practice a new hire adopts does not count. Intro paragraphs keep going to the extractor: when they do name a skill, it matters. But the prompt's "or that the work they describe uses" lets the model invent skills from general prose ("contribute to the product codebase" → `Refactoring`, `Code quality`).

## Outcome

Two stricter prompts were written and measured on the 9 labelled postings (see design.md, "Measurements"). Both cut wrong suggestions by about three quarters, but both lost 14–15 of the user's selected marks, against a limit of 3:

| | Wrong | Recall | Failed runs |
|---|---|---|---|
| Baseline (`atomic@2`) | 103 of 311 | 91/102 | 0 |
| `atomic@3` | 24 of 163 | 76/102 | 0 |
| `atomic@4` | 28 of 178 | 77/102 | 0 |

The second revision traded misses rather than reducing them, and further tuning on the same 9 postings would fit those postings rather than the task. The user decided:
- `atomic@2` stays the default.
- `atomic@4` is kept as a second skill extraction method, under its existing id, so its stored runs stay comparable and it can be measured again once the user has labelled and judged more postings.
- `atomic@3` is retired. Its runs stay viewable under their own id.

Choosing the method in settings or in `jobhunt eval`, comparing methods side by side, keeping later labels apart from these 9 postings, and recording why a suggestion was rejected belong to the follow-up change `accumulate-extraction-feedback`.

## What Changes

- **Two skill extraction methods side by side.** The skill extractors are registered by name and version. `atomic@2` (the prompt and retry text as they were before this change) is the default. `atomic@4` is the stricter method. Queued jobs and stored runs that name either keep working.
- **The stricter method (`atomic@4`):**
  - **Skills are named, not inferred.** It lists skills a line *names*, not skills derived from activities a line describes. A duty line that names a tool still yields that tool ("…via AWS Bedrock" → `AWS Bedrock`). A specialised practice the line names counts even when the line words it as work, and so does a discipline the line asks for experience in.
  - **A higher bar for what counts.** A skill is expertise a hiring team would screen for. New exclusions:
    - everyday activities that any engineer in the role does
    - basics any software engineer has or can learn quickly
    - team practices a new hire adopts
    - vague terms that name no particular expertise
    - kinds of data or records
    - kinds of past job
    - a bullet's label ("Evals:")

    Fields of study are excluded only when named as part of a degree. Only the excluded words are left out: other skills on the same line still count.
  - **Soft skills only when asked for as an ability.** "explain complex concepts to non-technical audiences" gives `Communication`. "partner with product managers" gives nothing.
- **Pipeline id.** The default stays `seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3`. Runs of the stricter method record `skills=atomic@4`.
- **No segmenter change.** Intro paragraphs stay required, as the user decided.

Out of scope:
- **Choosing the method** in settings or in `jobhunt eval`, and everything else listed for `accumulate-extraction-feedback` above.
- **The subject-domain rule.** The current prompt already excludes subject domains and names genomics as an example. The user marked `Genomics`, `Cybersecurity` and `statistical genetics` anyway, but has decided the rule stays as it is and that those marks were probably labelling mistakes.
- **A per-user "never suggest this skill" list (global rejection).** This is a possible follow-up change for preference-driven noise such as `Stakeholder management`.
- **Skill-name grouping** (`Azure` = `Microsoft Azure`).
- **Running models on the user's GPU without their go-ahead.**

## Success criteria

The criteria for making the stricter prompt the default were measured against the stored `atomic@2` runs, re-scored on the labels and judgments as of 2026-10-05 (no model calls): recall 91/102 and 103 wrong (rejected) suggestions out of 311 judged. A stricter prompt was to meet all of these on the same 9 postings:
- **Wrong suggestions at most half the baseline's** (at most 51 of 103).
- **Recall loss of at most 3 selected marks** compared with the baseline (at least 88/102).
- **0 failed runs.**

Neither `atomic@3` nor `atomic@4` met the recall criterion, so neither became the default. The change is complete when:
- With the default settings, `jobhunt eval` against a closed Ollama port reuses all 9 stored `atomic@2` runs and reports the baseline figures above (0 new runs, no model calls).
- Stored and queued `atomic@4` pipeline ids resolve to the stricter method.
- The tests pass on SQLite and Postgres.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `posting-enrichment`: "Step-wise extraction with replaceable steps" adds that at least two skill extraction methods, identified by name and version, exist side by side (`atomic@2` the default, `atomic@4`). A new requirement, "Stricter skill extraction", describes what `atomic@4` asks the model for. "Required and preferred skills" is unchanged, since it describes the default.

## Impact

- **Order.** `locate-quotes-on-whole-words` is applied and archived; the baseline above uses `v@3`.
- **Code.** `src/jobhunt/enrich/skills.py` (the two prompts and retry texts, one extractor class with a version per instance, `EXTRACTORS`), `src/jobhunt/enrich/pipeline.py` (the skill registry keyed by name and version, `DEFAULT_SKILLS`, `steps_from_id`).
- **Schema.** No migration.
- **Stored runs.** `atomic@2` and `atomic@4` runs are both reusable. `atomic@3` runs stay viewable, but a queued `atomic@3` job fails as "not available in this version", as for any retired step.
- **Tests.** Pipeline-id strings go back to `skills=atomic@2` (`tests/conftest.py`, `tests/test_enrich_pipeline.py`). The prompt tests cover both methods, and new tests cover both pipeline ids resolving.
- **Docs.** CLAUDE.md: the default pipeline id, the second method, and the project status. The labelling advice keeps the user's bar for what counts as a skill.
- **GPU.** 9 runs of about 30 s each for each measured version: `atomic@3` and `atomic@4`, both done with the user's go-ahead. The close-out needs no model runs.
