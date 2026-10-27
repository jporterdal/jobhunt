## Why

Scoring postings against the profile (`add-skill-match`) will treat a posting skill with no link as a gap. Today 152 of the 232 distinct posting skills have no link. Most of them are skills the CV doesn't name, which only the user can fix. But some are links the system should find and doesn't, and those would show up as false gaps mixed in with the real ones.

The user hand-linked 47 posting skills on `/profile/links` (on 2026-10-06). Leaving out the 6 that share a key with a profile skill, they give 28 links and 13 confirmed "no link" answers. The user checked each one, including those that repeat the model's link. They show where the current system fails:

- **The shortlist misses the right profile skill.** It embeds bare skill names, and nomic-embed-text scores short names by spelling, not meaning: `Model training` lands nearest to Mentoring and teaching, and `MCP` nearest to MSc Computer Science. For 3 of the 28 links, the right profile skill never reached the judge: `Reinforcement learning` (ranked 7th, outside the top 5), `Git` (14th) and `Claude Code` (40th of 48). Changing `SHORTLIST_K` or `SHORTLIST_FLOOR` can't fix a ranking this wrong.
- **The judge sometimes says "none" to a real link.** `Written communication` → `Communication` (similarity 0.91) and `ML/AI systems` → `ML techniques` were both judged `none`. The `link-judge@2` prompt tells the model "most are none", resolves doubt toward the weaker relation all the way down to `none`, and words `general` so that it reads like no match. On the other hand, it refused all 13 pairs the user confirmed as "no link", 8 of them after seeing plausible candidates, and agreed with the user on 22 of the 23 links it made. A fix must be narrow.
- **There is no way to measure a fix.** The last change's design asked for judging to be measured against hand-linked skills before the prompt changed again. Nothing does that yet, so a new prompt or retrieval method could only be judged by reading the links page.

This change comes before `add-skill-match`, so that the gaps it shows are as honest as linking can make them.

## What Changes

What was measured and what was adopted is in design.md, "Measurement results". In short: the app keeps finding candidates by bare names, and its judge becomes `link-judge@5`. Expansion and `link-judge@6` stay registered for later measurement. Everything else that was measured is deleted from the code.

- **Expanding skills, as a measured candidate-finding method (`skill-expand@1`).** A model step turns each skill into a few synonyms or short descriptive phrases, so the embedding search can compare meanings instead of spellings. The model sees the posting skill's name with its quote from the posting, or the profile skill's name with its evidence quote, so ambiguous names are read in context (`Attention`, `Lightning`, `Training`). Each phrase is embedded separately, and a candidate's similarity is its best-matching pair of phrases. Expansions are derived data, stored once per skill, step version and context, and shared by the app and the measurement. *Not adopted:* it finds concept-to-tool links bare names can't (`Vector databases` → `ChromaDB`), but brings candidates into confirmed refusals, and the paired comparison found it within noise of bare names. The app expands nothing while its method compares names.
- **Recording a merge's choice to rewrite profile skill phrasings.** A document job can carry the choice, and its merge records it, so that skills the document gives evidence for are expanded again from its wording. Without it, a profile skill keeps the phrasings made from its first evidence. The web interface doesn't offer the choice: with no expansion in the app it would have no visible effect. A change that adopts expansion adds it.
- **Judging versions.** `link-judge@3` (a looser `none`, a reworded `general`) and `@4` (one request per candidate) were measured and not adopted. `link-judge@5` is `@2` with its two examples taken from the user's own links replaced. It became the app's judge: within noise of `@2`, whose figures those examples flattered. `link-judge@6` is `@5` with each profile skill shown beside the CV line its evidence was found in; it was within noise of `@5` and stays registered. No judge's examples are pairs from the user's links, so measuring isn't flattered.
- **One linking method in the app.** There is no setting for the linking method. The code names the current method (candidate-finding and judging), and improving it means releasing a new version. When the version changes, the app re-judges by itself: posting skills whose latest judgment was made by another version are judged again, and their old links count until then. Measured methods that weren't adopted are deleted from the code, except one candidate for candidate-finding and one for judging, kept for later measurement.
- **Measuring links against the user's own links** (`jobhunt eval --links`). The command scores candidate-finding and judging against the user's link overrides, and is run during development, when the linking method is being improved or replaced. It judges overridden skills anyway, for measurement only, and reports:
  - how often the right profile skill is in the shortlist, and the average number of candidates (the judge's cost), across a range of shortlist sizes and floors computed from the same stored vectors
  - the judge's agreement on its own shortlist, and again with the right skill added to the candidates, so retrieval errors and judging errors are counted apart, with links to another skill that the judge tied with the user's choice counted apart
  - how many confirmed "no link" answers each method keeps
  - the current method and the others side by side, compared posting skill by posting skill, with a verdict (`better`, `worse`, `within noise` or `same`) and the skills where they differ.

  It reuses stored expansions and judgments, states how many model requests it needs before making any, and makes requests only for skills the user has linked, unless asked to preview every posting skill. Its judgments are stored in their own table, which the app never reads, so measuring never changes a link.
- **Adoption rule.** Each reference posting skill counts as right under a method when it gets the user's skill and relation, or keeps a confirmed refusal. Against the current method, a candidate is `better` when it fixes more posting skills than it breaks and a one-sided sign test puts the chance of so uneven a split at 0.05 or less, and `worse` in the opposite case. Anything else is `within noise`, because judging the same skill again flips a few answers. Adopting means making the candidate the current method in the code, normally only when it is `better`. `link-judge@5` was adopted within noise, with the user's approval, because `@2`'s lead came from its examples.

## Capabilities

### New Capabilities

- `link-evaluation`: measuring candidate-finding and link judging against the user's link overrides: the reference set, the command and its reuse of stored results, shortlist recall and candidate counts, judge agreement with and without the right candidate supplied, ties with the user's choice, kept refusals, a paired comparison with a sign-test verdict, the optional preview over all posting skills, and keeping measurement results out of the app.

### Modified Capabilities

- `skill-linking`:
  - "Links to profile skills": the app compares names, and a method that expands compares phrases. The app uses one linking method, named by the code.
  - "Re-judging when skills change": a change of the linking method's version re-judges, at start-up too, and the user adding or removing evidence counts as a skill change. Skills are expanded before planning when the current method expands.
  - "Link data kinds": expansions are derived data that is never edited. Measurement results are stored apart and never take effect.
  - New requirements: "Skill expansion" (only for a method that expands) and "Expansion context of a profile skill" (including the merge's recorded choice to rewrite phrasings).
- `enrichment-evaluation`: "Evaluation command" runs skill extraction only without `--links`.

## Impact

- **Order.** Before `add-skill-match`. Independent of the items in `FUTURE_CHANGE.md`. Item 2 there (eval runs leaking into the app) is the skill-extraction counterpart of keeping measurement results apart here. Follow-ups found while measuring are recorded there too.
- **Code.**
  - `enrich/expand.py` (new): the `skill-expand` step.
  - `enrich/links.py`: phrase-pair similarity, registered candidate-finding methods (`names`, `skill-expand@1`) and judges (`link-judge@5`, `@6`) with the current ones named in code, expansion before planning when the current method expands, the CV line beside each profile skill for `@6`, and the plan's version check.
  - `enrich/link_eval.py` (new): link measurement. `cli.py`: `eval --links`.
  - `enrich/derived.py`: writes expansions and measurement judgments.
  - `enrich/jobs.py`: carries the rephrase choice on document jobs, and queues judging at start-up after a version change.
  - `userdata.merge_run`: records the choice on the merge. `queries`: the expansion context of each profile skill and the CV line it was found in.
  - `tests/fakes.py`: `FakeLLM` answers expansion requests (top-level field `phrases`).
- **Data kinds.** Expansions and measurement judgments are derived data, written only by `enrich/derived.py`. Phrase vectors go in `skill_embeddings`, which is already keyed by embedded text. Overrides stay user-authored, and measuring only reads them. The merge's rephrase choice is user-authored. One Alembic revision (`0006`) adds the expansions and measurement tables and the merge column.
- **GPU.** Moving the app to `link-judge@5` means one automatic re-judging pass of every judged posting skill at the next `serve`. Measuring needs only requests for the overridden skills (about 50 judgments, plus about 100 expansions per new expanding method). Building and testing need no GPU.
- **Docs.** CLAUDE.md: the link pipeline id, one linking method with re-judging after a version change and at start-up, the measuring command and its verdict, the measured expansion step and its context rule, the rephrase choice (backend only), the `0006` backup note, and the updated known weak spots.
- **Out of scope.**
  - Completing the profile (the per-skill "I have this" review list), scores, credit per relation, and whether the relation set should be simplified: all `add-skill-match`.
  - Clean-up of profile skills that aren't skills (degrees, fragments such as `Chain`). The user deletes these by hand.
  - Clustering posting-skill variants (`LLM`, `LLMs`, `LLM APIs`).
  - Changes to the links page's override form.
  - The rephrase option in the web interface (with a change that adopts expansion).
