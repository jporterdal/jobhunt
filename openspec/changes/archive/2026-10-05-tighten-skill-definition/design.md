## Context

`AtomicExtractor` (`src/jobhunt/enrich/skills.py`, `atomic@2` before this change) sends `SKILLS_SYSTEM` plus numbered lines, once per group (required, preferred). If a group comes back empty, it retries once with `EMPTY_REMINDER` appended, and fails the run if the group is still empty. Segmentation (`llm-lines@2`) labels intro paragraphs about the role as required. The user has decided to keep that: a skill named in an intro paragraph should be suggested, as required.

Every new rule below was checked against the user's mark names (172 when D1–D6 were written, 222 by 2026-10-05), so that no exclusion example names something the user marked. For example, the user marked `machine learning`, `Software development`, `Communication`, `Mentoring`, `CI/CD`, `Git` and `Containers`, so none of these appear as exclusions.

### Measurements

`atomic@3` (D1–D6 only) and `atomic@4` (D1–D9) were each run on the 9 labelled postings on 2026-10-05, against the `atomic@2` baseline re-scored on the same labels. The baseline was re-scored again before the `atomic@4` run, with identical figures.

| | Wrong | Recall | Failed runs | Unjudged |
|---|---|---|---|---|
| Baseline (`atomic@2`) | 103 of 311 | 91/102 | 0 | 0 |
| `atomic@3` | 24 of 163 | 76/102 | 0 | 3 |
| `atomic@4` | 28 of 178 | 77/102 | 0 | 7 |

**`atomic@3`.** Wrong suggestions met the target, but recall lost 15 marks (19 newly missed, 4 recovered), against a floor of 3. The newly missed marks:
- **Expertise worded as work (10):** `LLM evaluation` ×3, `Evaluating LLM agentic solutions`, `AI evaluation frameworks`, `benchmark model performance`, `Feature engineering`, `agentic loops`, `Agent skill authoring`, `numerical optimization`. D1's "do not work out skills from what a line says the job involves" and D2's activities exclusion both drop them.
- **Broad disciplines (5):** `data science`, `software engineering`, `cloud development`, `cloud-native SaaS`, `product analytics`, read as vague terms or fields of study.
- **Named skills dropped along with an excluded item (3):** `CI/CD`, `LLM APIs`, `AI application security` (all on posting A). Both CI/CD lines also contain excluded items (YAML; architecture, code reviews, Agile).
- **`Technical communication` (1)** on posting B.

Its 24 wrong suggestions were 11 named tools or methods the user rejected (left to the global-rejection follow-up), 9 vague terms, 3 architecture styles or basics and 1 soft skill (`Technical leadership`, named in the posting). D7–D9 revised the prompt to `atomic@4`.

**`atomic@4`.** Compared with `atomic@3` it recovered 6 marks (`data science`, `cloud development`, `software engineering`, `Feature engineering`, `LLM APIs`, `AI application security`) and lost 5:
- `Technical communication` ×2. On posting C it returned nothing for "Clear communication, able to explain technical findings to technical and non-technical audiences", close to the prompt's own example.
- `PhD in computer science` (it gave `Advanced degree` and `Electrical engineering`, a field of study named as part of a degree), `Jupyter notebooks` and `cloud-native compute infrastructure`, all found by `atomic@3`.

Still missed by both: every "evaluation …" mark (frameworks, harnesses, pipelines, ×4), `CI/CD`, `benchmark model performance`, `numerical optimization`, `agentic loops` and `Agent skill authoring`. D7 and D8 reached none of them. The 28 wrong suggestions were the same 11 tools and methods, 10 vague practices worded as work that D7 let back in (`Statistical techniques`, `Simulation`, `Data pipelines`, `Prompting`, `Tool use`, `Multi-step workflows`, `Observability`, `Secure development`, `LLM application development`, `AI models`), 4 architecture styles or basics, 2 subject-domain items and `Technical leadership`. One unjudged suggestion, `Experiment design`, copied the name of a D7 example.

Spec scenarios on the `atomic@4` run: "Discipline asked for" passed; "Practice worded as work", the CI/CD line of "Activities, basics and team practices are left out", and "Soft skill asked for as an ability" (as worded on posting C) failed.

**Reading.** Each revision moved recall by about one mark while changing which marks were found. The 12B model responds to the prompt's wording more than to its rules, and 9 postings cannot separate the two. Tuning further on the same postings would fit them rather than the task. D10–D11 close the change.

## Goals / Non-Goals

**Goals:**
- Stop the model inventing skills from described activities. This matters most in intro paragraphs.
- Encode the user's bar: expertise worth screening for.
- Make the effect measurable without another review pass (see proposal, "Success criteria").
- After the measurements: keep the stricter prompt runnable beside the default, so it can be measured again on a larger labelled set.

**Non-Goals:**
- Changing segmentation.
- Deterministic filtering (a stoplist or post-filter). It is left out so that the eval measures the prompt alone (see D5).
- Choosing the skill extraction method in settings or `jobhunt eval`, and side-by-side comparison (`accumulate-extraction-feedback`).
- Changing the subject-domain exclusion. The user has decided it stays, and that their `Genomics`, `Cybersecurity` and `statistical genetics` marks were probably labelling mistakes.

## Decisions

### D1. "Names" replaces "asks for, or that the work they describe uses"

The opening becomes: *List every skill the numbered lines name, one skill per entry. Only list a skill whose name, or a clear form of it, appears in the line. Do not work out skills from what a line says the job involves.*

This is the main lever on intro paragraphs (the user's point (a): they rarely contain skills). It also targets the 25 activity rejections and the 12 intro-paragraph ones. Duty lines still give named tools, since "…via AWS Bedrock" names AWS Bedrock.

*Alternative:* tag paragraph lines in the user message (deterministically, by line shape) and apply a stricter rule to them. Not taken now, because two levers changing at once can't be told apart in one eval. It is the first fallback if intro-paragraph rejections persist (see Risks).

### D2. The bar, and the exclusion list with examples

Add a short definition, then examples taken from the user's rejections:

```
List only skills a hiring team would screen for: expertise that takes real study or practice to gain.
Do not list:
- everyday activities that any engineer in the role does (for example refactoring, debugging,
  code reviews, bug fixing, on-call rotation, prototyping, defining KPIs or success metrics)
- basics that any software engineer has or can learn in an afternoon (for example YAML, unit testing, A/B tests)
- team practices a new hire adopts rather than brings (for example Agile, Scrum, SOLID principles, design patterns)
- vague terms that name no particular expertise (for example "AI technologies", "AI tools", "coding",
  "architecture", "implementation")
- kinds of data or records (for example EHRs, claims, imaging, registries)
- kinds of past job (for example professional services, solutions engineering)
- the label before a colon that starts a line ("Evals:", "Coding agents:"); take skills from the text after it
```

These go after the existing exclusions (traits, industries and domains, fields of study, fragments), which stay word for word except for the fields-of-study narrowing in D7. `atomic@3` worded the first item "activities the job involves rather than expertise it needs"; D7 narrows it.

### D3. Soft skills only when asked for as an ability

Replace the soft-skill example "(for example communication, stakeholder management, technical leadership)" with "(for example communication, mentoring)". Add: *List a soft skill only when the line asks for it as an ability: "explain complex ideas to non-technical audiences" gives Communication; "partner with product managers" gives nothing.*

`Stakeholder management` (5 rejections) and `Technical leadership` (2) were examples the prompt itself handed the model. Removing them matters as much as the new rule.

### D4. `EMPTY_REMINDER` no longer pushes toward inferred skills

The reminder currently says that the lines "ask for at least one skill, or describe work that uses at least one". That contradicts D1. It becomes: *These lines come from the {group} section of a job posting. List every skill they name.* The existing test asserts only on "required section", so it keeps passing.

### D5. No deterministic filter in this change

A stoplist of rejected names would raise precision immediately, but it would hide whether the prompt works. Preference-driven noise is better handled by a user-owned global rejection, which can be its own change. The eval would then count it as wrong-but-hidden or not at all; that decision belongs to that change.

### D6. The stricter prompt is `atomic@4`

The output changes, and `atomic@3` runs are stored, so the D7–D9 revision needs its own version; old runs stay viewable under their own id. After D10 the default pipeline id stays `seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3`, and runs of the stricter prompt record `skills=atomic@4`.

### D7. Practices and disciplines named as work count

After "Do not work out skills from what a line says the job involves." add:

```
A specialised practice the line names is a skill even when the line words it as work: "design experiments to
test pricing changes" gives Experiment design; "tune database performance under load" gives Performance tuning.
A discipline the line asks for experience in is a skill: "5+ years of site reliability engineering" gives
Site reliability engineering.
```

This targets the 10 expertise-worded-as-work misses and the broad disciplines. To keep it from contradicting D2, the activities exclusion narrows to "everyday activities that any engineer in the role does" (same examples), and "fields of study" narrows to "fields of study named as part of a degree ("PhD in physics" gives PhD, not Physics)". The old wording likely made the model treat a required discipline as a degree subject. The subject-domain rule is unchanged.

### D8. Leave out only the excluded words

After the D2 list add: *Leave out only the excluded words, not the whole line: "write YAML manifests for Kubernetes" gives Kubernetes.* This targets CI/CD and the other named skills dropped along with an excluded item on the same line.

### D9. Examples avoid the user's mark names

Positive examples in D7 and D8 name nothing the user marked. `Model evaluation`, `Data engineering`, `MLOps` and `Query optimization` are marked, so they are not used: teaching the model the eval's answers would inflate recall.

### D10. Keep `atomic@2` as the default and `atomic@4` beside it

Neither stricter prompt met the recall criterion (see "Measurements"), and the user chose to keep the default while collecting more labels and judgments. While collecting, a prompt that suggests more is more useful: every suggestion the user accepts or rejects is a judgment that can be measured later, while a missed skill produces no data unless the user marks it by hand.

- `AtomicExtractor` takes its version, prompt and retry text per instance. `EXTRACTORS` holds `atomic@2` (the prompt and retry text from before this change, restored word for word from commit `128f5a3`) and `atomic@4`.
- `pipeline.skill_extractors()` is keyed by `name@version`, `DEFAULT_SKILLS` becomes `"atomic@2"`, and `steps_from_id` looks the skill step up by its full `name@version`. Segmenters and salary extractors keep their name-only keys; they have one version each.
- `atomic@3` is not kept: it was measured once and superseded by `atomic@4`. Its runs stay viewable; a queued `atomic@3` job fails like any job naming a retired step.

*Alternative:* rename the stricter prompt (`strict@1`). Not taken: its 9 stored runs would no longer match, so measuring it again would cost another 9 GPU runs. *Alternative:* make `atomic@4` the default (option 1). Not taken: the user chose recall while collecting data.

### D11. The spec describes the stricter request, not the model's behaviour

The `atomic@3`/`atomic@4` spec scenarios described model output ("a skill is suggested for CI/CD"), and the measurement showed the model doesn't reliably produce it. "Stricter skill extraction" therefore specifies what the request asks for, which tests can check, and leaves the behaviour to `jobhunt eval`. The failed scenarios are recorded under "Measurements", so they can be checked again when the method is measured again.

## Risks / Trade-offs

- [A 12B model follows only part of a longer prompt] → This happened (see "Measurements"). The stricter prompt is kept, not adopted.
- [Revisiting `atomic@4` on postings that shaped it] → Its prompt was revised against these 9 postings. `accumulate-extraction-feedback` reports postings labelled later separately, so a future comparison is not flattered by them.
- [A stricter bar empties a group, especially a short preferred group ("Prior startup experience"). Two empty answers fail the run] → Neither measured run failed. If later runs fail, whether an empty group after the retry may be stored as empty is a spec question for the user.
- [Recall drops because the model also drops things the user marked, such as `Problem solving`, `Software development` or `Algorithms`] → This happened (14–15 marks lost), and is why the stricter prompt is not the default.
- [Intro-paragraph rejections persist] → Fallback: tag paragraph lines (D1 alternative) as a later version, measured on the larger labelled set.
- [The default keeps `atomic@2`'s noise: about a third of its judged suggestions are wrong] → Accepted while collecting judgments; the global-rejection follow-up targets the named tools the user rejects.
- [Model behaviour can't be guaranteed by unit tests] → D11: the spec states what the request asks for; the eval and the recorded scenario checks (on posting A, posting D, posting E, posting F, posting G) measure behaviour.

## Migration Plan

No schema change. Old runs remain viewable under their own pipeline id. The default pipeline id is the one before this change, so stored `atomic@2` runs are reused as before. Rollback is a revert.
