## Context

See proposal.md for motivation. The current state this design builds on:

- **Linking today** (`enrich/links.py`, archived design `add-cv-skill-profile` D8–D10). One `links` job embeds each skill's bare name (`clustering: ` prefix for nomic-embed-text, vectors in `skill_embeddings` keyed by `(model, text_key)`), shortlists up to `SHORTLIST_K = 5` profile skills at cosine ≥ `SHORTLIST_FLOOR = 0.75`, and makes one `link-judge@2` request per posting key with candidates. `plan` re-judges a key when its candidate set or embedding model differs from its latest judgment's. `queries.effective_links` uses the latest succeeded judgment, whatever its pipeline. Judgments are stored with `pipeline = "links=link-judge@2"`.
- **Context in requests.** The judge sees the posting skill's name and one quote (`queries.posting_skill_keys` keeps the first one it meets), and each candidate's oldest evidence quote (`links.evidence_quotes`).
- **Evidence and merges.** `skill_evidence` rows carry `document_id`. A merge logs every row it inserts in `profile_merge_changes`, and `rollback_merge` deletes them. A document job's `pipeline` is checked by `cv.check_pipeline`. A links job already carries a scope suffix (`ALL_SCOPE`) on its pipeline.
- **Stored data on 2026-10-06.** 232 posting keys, 48 profile skills, 271 vectors, 223 judgments each by `@1` and `@2`. The overrides have grown since the handoff's baseline (47 overrides: 28 links, 13 refusals): there are now 55, of which 5 share a key with a profile skill, none is stale, and 29 links and 21 refusals remain. numpy is not installed.
- **The skill-extraction eval stores its runs with the app's** (`FUTURE_CHANGE.md`, item 2): 9 of the 10 postings with runs show `atomic@4` suggestions because an eval ran it last. Link measurement must not repeat this.

## Goals / Non-Goals

**Goals:**
- Candidates are found by meaning, so the right profile skill reaches the judge.
- The judge recovers broader-skill links without losing confirmed refusals.
- Every change to linking can be measured from stored data, with the GPU used only for what is new, and measuring never changes what the app shows.
- The app has one linking method, and changing it is a code release followed by automatic re-judging.

**Non-Goals:**
- Making the user's relation usage the prompt's definitions (`Technical communication` → `Communication` as `related`, a BSc → PhD as `general`). That's input for `add-skill-match`.
- Keeping several linking methods selectable in the app, or keeping superseded methods runnable after adoption.
- Re-measuring skill extraction, or fixing the skill-extraction eval leak (`FUTURE_CHANGE.md`, item 2).
- Changing the links page.

## Decisions

### D1. The expansion step (`skill-expand@1`)

A new module `enrich/expand.py` holds the step: one chat request per skill, with the usual fixed options (temperature 0, seed 7, context size, `think: false`) and a JSON schema whose top-level field is `phrases` (array of strings), so `FakeLLM` can script it.

- **Input.** The skill's name, and its context quote when it has one ("In the posting: …" or "On the CV: …").
- **Prompt.** Asks for up to six alternative phrasings: synonyms, the expanded form of an abbreviation, the usual name of the tool or practice, and a short description that names what kind of skill it is ("Claude Code" → "AI coding agent"). It asks the model to read the context to decide what an ambiguous name means, and not to list broader skills, narrower skills or related tools, which would turn the shortlist into a topic search.
- **Cleaning.** Trim, collapse whitespace, drop phrasings whose `name_key` equals the name's or an earlier phrasing's, drop phrasings over eight words, keep at most six. No quote check: phrasings are not claims about the text.
- **Model.** The chat model from Settings, recorded with the expansion. A change of chat model doesn't re-expand, just as it doesn't re-judge.
- **Storage.** `skill_expansions` (derived, never edited): `id, side ('posting'|'profile'), skill_key, skill_name, context (nullable text), step ('skill-expand@1'), model, status, error, phrases_json, created_at, output_json`, indexed on `(side, skill_key, step)`.
- **Lookup.** A posting skill uses its newest succeeded expansion at the current step, whatever its context. It's expanded once per step version, so new postings don't churn it. A profile skill uses its newest succeeded expansion at the current step whose `context` equals its current context (D2). A failed or missing expansion means the skill is compared by name alone in this pass, and the next links job asks again.

*Alternative:* one vector per skill for all phrasings joined together. Not taken: the joined vector averages the meanings back toward the name, which is what failed.

### D2. Expansion context, and rewriting phrasings from a document

- **Posting skills.** The quote `posting_skill_keys` gives (unchanged).
- **Profile skills.** `queries.expansion_contexts(conn)` returns `skill_id → (evidence_id, quote)`, chosen in order:
  1. The first evidence row (lowest id) that the newest non-rolled-back merge with `rephrase` inserted for the skill. Found through `profile_merge_changes` rows with `table_name='skill_evidence'` and `action='insert'`.
  2. Otherwise, the oldest evidence row.
  3. Otherwise, none.

  The judge shows each candidate with the same quote, replacing `evidence_quotes`, so expansion and judging see the same context.
- **The option.** A document job can carry the choice to rewrite phrasings: `jobs.enqueue_document(..., rephrase=True)` appends ` rephrase` to the job's pipeline, the same way links jobs carry `ALL_SCOPE`, and widens an already-queued job for the same document. `cv.check_pipeline` accepts the suffix. `_run_document` passes it to `merge_run(conn, run_id, rephrase=...)`, which stores it in the new column `profile_merges.rephrase` (user-authored, written by `userdata`). "Merge again" reuses the merge's stored value.
- **No checkbox (decided 2026-10-06, with the user).** The plan was a checkbox, "Rewrite skill phrasings from this document", on the upload and "Add to profile" forms (group 7, and a `profile-extraction` delta). Expansion wasn't adopted, so the app's method never reads an expansion context, and the checkbox would change nothing the user can see. The backend stays, because measuring `skill-expand@1` uses the context rule. A change that adopts expansion adds the checkbox and the `profile-extraction` requirement.
- **Why the merge, not the skill.** Rollback already removes the merge's evidence, so the context falls back with no extra bookkeeping (spec scenario "Rolling back the rewriting merge"), and the old expansion is found again by its context text.

*Alternative:* re-expand whenever a profile skill's evidence changes. Not taken: merges add evidence often, each re-expansion is GPU work and can move shortlists, and the user wants to choose per document.

*Accepted consequence:* a skill added by hand without evidence is expanded with no context, then again when it first gets evidence (by hand or by merge). Deleting the evidence that is the context also re-expands. Both are rare and reasonable.

### D3. Phrase-pair similarity and the shortlist

- **Phrases.** A skill's phrases are its name plus its expansion's phrasings. Each is embedded on its own with the model's prefix (`clustering: ` still applies) and stored in `skill_embeddings` under `name_key(phrase)`. Phrases shared between skills are embedded once.
- **Similarity.** A profile skill's similarity to a posting skill is the maximum cosine over all phrase pairs. Keeping the name as a phrase means bare-name matches are never lost. Vectors are normalised once per pass, so each pair is one dot product. The shortlist records each candidate's similarity and its best pair (`candidates_json` gains `pair`), which the measurement's JSON shows.
- **Cost.** Pure Python, measured at about 11 µs per 768-dimension dot product: today's 232 keys × 48 skills × ~7 × 7 pairs is about 6 s of CPU per links pass. That's acceptable in a background job. numpy would cut it sharply but isn't a chosen dependency (see Open Questions).
- **Shortlist constants per method.** Each candidate-finding method carries its own size and floor: `names` keeps 5 and 0.75. `skill-expand@1` starts at 5 and 0.75, and both are set from the measurement's sweep before adoption (task 6.3). Max-pair similarities run higher than bare-name ones, so the floor will likely rise.

**Measured on 2026-10-06 (task 6.3): not adopted.** See "Measurement results". Expansion shortlisted 27 of 29 reference links against 26 for bare names, but phrase-pair similarities sit at 0.75 or more for almost every pair, so every shortlist filled to 5 and no confirmed refusal was left without candidates (11 of 21 are under `names`). The sweep shows no floor below 0.80 cuts anything, and at 0.85 it shortlists fewer links than `names` does at 0.75 (24 against 26). No size or floor was chosen, because the judging results rule expansion out at any of them.

*Alternative:* retune `SHORTLIST_K` / `SHORTLIST_FLOOR` on bare names. Not taken: `Claude Code`'s right skill ranks 40th of 48 by name, so no cutoff that keeps the judge's cost sane reaches it.

*Alternative:* send every profile skill to the judge. Not taken: with 48 profile skills that means 48 judgments in one request from a 12B model, and it gets worse as the profile grows ("I have this" in `add-skill-match` adds skills).

### D4. One linking method, named by the code

`links.py` keeps two small registries: candidate-finding methods and judges. It also has `CURRENT_RETRIEVAL` and `CURRENT_JUDGE`. The app's pipeline id is built from the current pair: `links=link-judge@2` for `names` + `@2` (identical to the pipeline before this change, so nothing was re-judged during development), and `expand=skill-expand@1 links=…` for a method that expands. At the end of this change the registries hold `names` (current) and `skill-expand@1`, and `link-judge@5` (current, pipeline `links=link-judge@5`) and `link-judge@6`.

- **No setting.** The user is also the developer, so rolling back is a one-line change followed by automatic re-judging. A Settings choice (the `llm.skills` pattern) would add UI, spec surface and a mixed-version state for no benefit here.
- **Version-change re-judging.** `plan` also re-judges a key whose latest judgment's `pipeline` differs from the current one. Its old link stays in effect until the new judgment is stored, so links never disappear mid-upgrade.
- **Start-up.** `serve` (after `jobs.recover`, not in the reloader's parent) calls `jobs.enqueue_links_if_outdated`. It queues a links job only when some posting key's latest judgment has another pipeline. Otherwise a version change would wait for the next unrelated trigger.
- **After adoption** the superseded entries are deleted from the registries, keeping the current method and at most one candidate under test for each part. Their judgments stay in `link_judgments` and `link_measurements` as history, but `eval --links` can no longer re-score them, so their figures are kept in this design ("Measurement results"). Deleted on 2026-10-06: `link-judge@2`, `@3`, `@4`, `matched@1` and `matched-trim@1`, with the scoring code only they used (matched mean, drift trimming, one request per candidate).

### D5. `link-judge@3`

The same request and schema as `@2`, with a revised system prompt:
- `none` is defined as "none of the four relations applies", not as "anything else", and "most are none" is removed.
- `general` is worded as "the CV skill is a broader skill that the posting's skill is part of". The phrase "having it doesn't show the posting's skill" is removed, because it reads like no match.
- Doubt resolves to the weaker of the *linked* relations (same → specific → general → related). `none` is not a step on that ladder.
- Refusal examples are plainly unrelated pairs. The rule against pairs that only share a word or a broad field stays, without near-miss examples.
- `same` stays strict, with `@2`'s wording.

**Measured on 2026-10-06 (task 6.3): not adopted, and deleted from the code.** See "Measurement results". With bare-name candidates, `@3` had 18 of 29 links right against `@2`'s 23, and kept 17 of 21 refusals against 21. Loosening `none` made the judge link more, and most of the extra links went to the wrong profile skill.

**Examples are never pairs from the user's overrides** (no `Written communication` → `Communication`), so the measurement isn't flattered. This is the linking counterpart of "accept, don't select" in skill labelling. A test checks that no example pair matches an override in the test fixtures. The real check is by hand, against the user's real overrides (task 6.1).

### D6. The links job, in order

1. **Expand.** Every profile skill and every posting key to be judged (no override, no same-key profile skill) that lacks a usable expansion (D1). One request each, each stored in its own transaction. Cancellable between requests.
2. **Embed** every phrase without a stored vector, batched, as today.
3. **Plan.** Shortlist by phrase-pair similarity. Select keys never judged, or whose candidate set, embedding model or pipeline differs from their latest judgment's ("Re-judge all": every key).
4. **Judge**, as today, with the current judge and context quotes (D2).

Steps 1 and 2 run only when the current method expands. With `names` current, the job behaves exactly as today. New triggers for `enqueue_links`: evidence added or removed by the user (`userdata`), and start-up after a version change (D4).

### D7. Link measurement (`enrich/link_eval.py`, `jobhunt eval --links`)

- **Command.** `jobhunt eval --links [--retrieval A,B] [--judge X,Y] [--model M] [--fresh] [--dry-run] [--all-skills] [--json] [--db URL] [--ollama-url URL]`. A flag on `eval`, not a subcommand, because it runs only in development cycles and shares `eval`'s options, and the `llm-connection` "Configured Ollama address" requirement already covers `eval`. `--skills` and `--segmenter` are refused with `--links`. It runs every retrieval × judge combination. The app's current pair comes first when listed (D4 defaults).
- **Reference set** from `skill_link_overrides`, as the spec says. Posting names and quotes come from `posting_skill_keys`.
- **Plan, then execute**, as in `evaluate.py`. The plan counts the missing expansions (overridden posting keys and all profile skills, for expanding methods), the missing phrase vectors, and the judgments with no reusable result. It prints them and stops on `--dry-run`. Execution stores each result as it's made, so an interrupted run keeps its work.
- **Reuse key for judgments**: posting key, judge version, chat model, embedding model, and the *ordered* candidate list (the judge numbers candidates in shortlist order, so a different order is a different request). Searched in `link_measurements`, then in `link_judgments` (judge version parsed from the `links=` part of `pipeline`). The second lookup reproduces the `names` + `link-judge@2` baseline from stored data with few or no requests. `--fresh` skips judgment reuse only. Expansions are shared with the app (same step, same context, same output), so a fresh one would only duplicate.
- **Right skill added.** For a reference link whose skill isn't shortlisted, a second judgment is made with the skill inserted at its similarity rank. Its reuse key differs by candidate list, so no special mode column is needed.
- **Sweep.** Sizes 3, 5, 8, 10, 15 × floors 0.60–0.85 in steps of 0.05, computed from the stored vectors of the reference keys. Each cell shows shortlisted links / 29 and the mean candidates per reference key. Cost is measured over the reference set only: measuring it over every posting key would need expansions for all of them.
- **Verdict** as the spec defines: a paired comparison with the first combination, posting skill by posting skill (a right link or a kept refusal counts as right), with a one-sided exact sign test over those fixed and broken. `better` and `worse` need p ≤ 0.05; otherwise `within noise`. This replaced the first rule (any loss of links or refusals was `worse`), which the third round showed was too strict for a set this small.
- **`--all-skills` preview.** Expands and judges every judged posting key for each combination, and reports how many are linked and how many differ from `effective_links`. It's opt-in because it's roughly five times the GPU work, for answers nobody can score.
- **Storage.** `link_measurements` (derived, written by `derived.save_measurement`, read only by `link_eval`): `id, posting_key, posting_name, judge, model, embed_model, candidates_json, status, error, relations_json, created_at, output_json`. The app never reads it, so it needs no filter. That's the reason for a separate table over a flag column on `link_judgments`.

*Alternative:* compare a new method's links with the links the app has stored. Not taken: those are the current method's output, so the comparison shows disagreement, not correctness. Only the user's overrides have a known right answer.

### D8. Schema: `0006_skill_expansion`

- Adds `skill_expansions` and `link_measurements` (both in `DERIVED_TABLES`).
- Adds `profile_merges.rephrase` (Boolean, not null, server default false).
- `downgrade()` strips ` rephrase` from queued document jobs' pipelines (`replace()` works on both databases), drops the column with `render_as_batch`, and drops both tables.

### D9. Tests

- **Fakes.** `FakeLLM` scripts `phrases` answers. `FakeOllama`'s trigram embeddings work on phrases unchanged, so tests can make a phrase pair beat bare names.
- **Expansion.** Cleaning (identity duplicates, length, cap), lookup by side and context, failure falls back to name only and retries next job, chat-model change doesn't re-expand.
- **Context.** Rephrase on and off, rollback restores the old context and reuses the old expansion, a hand-added skill getting its first evidence, widening a queued document job.
- **Planner.** Max-pair similarity, pipeline mismatch re-judges with old links kept until replaced, `names` current behaves exactly as before, start-up enqueue only when outdated.
- **Measurement.** Reference-set exclusions, each judging count, right-skill-added counts, sweep, verdicts, reuse from `link_judgments` and from its own table, `--fresh`, `--dry-run` request counts, exit codes, the preview, and that nothing it stores changes `effective_links` or the plan.
- **Migration.** `tests/test_migrate.py`, on Postgres too.

## Measurement results (2026-10-06)

`jobhunt eval --links --retrieval names,skill-expand@1 --judge link-judge@2,link-judge@3` on the real database, with gemma4:12b and nomic-embed-text. The reference set is 29 links and 21 confirmed refusals, with 5 overrides left out as same identity. The run made 98 expansions, embedded 474 phrases and made 186 judgments, 3 of them for `names` + `@2` and the rest reused from the app.

| Linking method | Right skill and relation | Right skill, other relation | No link, right skill a candidate | Another skill | Right skill not a candidate | Refusals kept | Verdict |
|---|---|---|---|---|---|---|---|
| `names` + `@2` (current) | 23 | 1 | 2 | 0 | 3 | 21 of 21 | — |
| `names` + `@3` | 18 | 3 | 1 | 5 | 2 | 17 of 21 | worse |
| `skill-expand@1` + `@2` | 13 | 2 | 2 | 11 | 1 | 15 of 21 | worse |
| `skill-expand@1` + `@3` | 9 | 5 | 0 | 14 | 1 | 8 of 21 | worse |

**Decision: keep `names` + `link-judge@2`.** All three candidates are `worse` by the proposal's rule, so none is adopted (task 6.4). What the figures show:

- **Judging, not candidate finding, limits the current method.** With the right skill added to every shortlist that lacked it, `names` + `@2` still has 23 right. Of its three candidate misses (`Claude Code`, `Git`, `Reinforcement learning`), none becomes right when the skill is added.
- **More candidates make the single-link rule pick other skills.** One link is kept per posting skill, the strongest relation. Expansion puts 5 candidates in every shortlist, so a closer-sounding profile skill often wins. Examples are `agent frameworks` → `agent orchestration` (`same`) instead of `agentic AI workflows`, and `Mathematical modeling` → `Adaptive Penalty Methods` instead of `numerical optimization`.
- **Some "another skill" results are defensible.** `MSc Computer Science` for `Master's degree`, `Advanced degree` and `Computer science undergraduate degree`, and `neural networks` for `representation learning`, are links the user might accept. Counting those four as right, expansion + `@2` reaches about 17, still below 23, and it breaks 6 refusals. The reference set allows one right answer per posting skill, so it understates any method that finds a different valid link.
- **Context rarely helps expansion.** Most posting quotes and CV evidence quotes are the skill's own words ("Git", "SQL", "agentic AI workflows"), because extraction quotes only the skill. `Attention` (quote: "attention") was expanded as the soft skill ("Concentration", "Focus"). An expansion step would need the whole line the quote is in.
- **`@2`'s own example is a user override.** `@2` uses "Java" for "C#" as its `related` example, and the user linked `C#` → `Java` as `related`. So `@2`'s result on `C#` is flattered by one link. `@3` avoids it, and its examples were checked by hand against the real overrides (task 6.1).
- **The baseline matches the handoff.** The handoff had 25 of 28 links shortlisted and 22 right, with all refusals kept. With one more reference link it is 26 of 29 and 23 right, and all 21 refusals are kept.

### Second round: scoring phrase pairs (2026-10-06)

Taking the most similar of about 49 phrase pairs raised every similarity: 45% of pairs reached 0.75, against 7% for bare names. Scores were compared offline on the stored vectors (no requests), by the right skill's rank and by how well a floor separates right skills from refusals' best candidates:

- **Mean ÷ variance**, and mean minus one or two standard deviations, ranked worse. A real match has a few very high pairs and many middling ones (high spread), while unrelated skills sit at about 0.65 throughout (low spread). So penalising spread penalises real matches. Mean ÷ variance put the right skill below almost every other skill.
- **Matched mean** pairs each phrase with its most similar phrase of the other skill, averages those best matches both ways, and averages the two directions. It ranked best: 28 of 29 right skills in the top 5, and 2.6 candidates per skill at floor 0.78, as many as names pass at 0.75. Registered as `matched@1`.
- **Matched mean with drifted phrasings dropped** (phrasings below 0.80 similarity to their own name) separated refusals best. Registered as `matched-trim@1`, size 5, floor 0.77. Both were deleted at the end of the change.

Judged with `@2`:

| Linking method | Right skill and relation | Right skill, other relation | No link, right skill a candidate | Another skill | Right skill not a candidate | Refusals kept | Verdict |
|---|---|---|---|---|---|---|---|
| `names` + `@2` | 23 | 1 | 2 | 0 | 3 | 21 of 21 | — |
| `matched@1` + `@2` | 16 | 3 | 0 | 8 | 2 | 17 of 21 | worse |
| `matched-trim@1` + `@2` | 18 | 4 | 2 | 3 | 2 | 21 of 21 | worse |

**Not adopted.** `matched-trim@1` keeps every refusal. Of the 5 links it loses against `names`, only one is lost by candidate finding (`Problem solving` → `Algorithms` left the shortlist). Two are ties: `MSc Computer Science` was judged the same relation as the user's choice, ranked first and won, for `Master's degree` and `Computer science undergraduate degree`. Two are the judge answering differently for the same pair in another list: `representation learning` → `ML techniques` went from `general` to `none`, and `LLM-based agents` → `agent orchestration` from `related` to `specific`. Its gains (`Reinforcement learning`, `Written communication`) found the right skill but with another relation. With 29 reference links, the judge's instability and the tie rule outweigh the shortlist's effect, so shortlist methods can't be compared reliably until judging is stable.

### Third round: the judge (2026-10-06)

Two judge versions were measured against `@2`, on the same shortlists:

- **`link-judge@4`** has `@2`'s definitions but judges each candidate in its own request. Measurement reuses pair answers across candidate lists. Deleted at the end of the change.
- **`link-judge@5`** is `@2` with only its two examples taken from the user's own links replaced: "Java" for "C#" is an override, and "Operating systems" for "Docker" a confirmed refusal.

| Linking method | Right skill and relation | Right skill, other relation | No link, right skill a candidate | Another skill | Right skill not a candidate | Refusals kept |
|---|---|---|---|---|---|---|
| `names` + `@2` | 23 | 1 | 2 | 0 | 3 | 21 of 21 |
| `names` + `@4` (one candidate per request) | 16 | 4 | 5 | 1 | 3 | 21 of 21 |
| `names` + `@5` (`@2`, neutral examples) | 19 | 2 | 3 | 2 | 3 | 21 of 21 |
| `matched-trim@1` + `@4` | 14 | 3 | 5 | 4 | 3 | 21 of 21 |
| `matched-trim@1` + `@5` | 17 | 3 | 4 | 3 | 2 | 20 of 21 |

**Not adopted.** What the figures show:

- **Judged alone, the model is stricter.** On identical pairs, 6 of 13 `related` and 2 of 6 `general` answers became `none`. The user's links are mostly comparative ("the closest skill I have"), and judging within a list matches that better. List context is part of what makes `@2` agree with the user, not only noise.
- **`@2`'s baseline is flattered by its examples.** With only the two examples changed, `C#` → `Java` and `.NET` → `Java` were lost, which is the example's direct effect. Two other links (`Problem solving`, `representation learning`) moved to an equally related profile skill. A neutral-example `@2` scores 19, not 23.
- **The measurement's noise is about ±2–4 links.** Changing two examples moved 4 of 29 links. Differences of that size between methods can't be read as better or worse with 29 reference links, and the verdict rule (any loss is `worse`) is too strict for a set this small.

**Afterwards: a paired verdict, and `@5` made current.** The verdict rule was replaced by a paired comparison. Each reference posting skill counts as right (a right link, or a kept refusal) or not under each method. The report counts those a method fixes and breaks against the base, with a one-sided exact sign test. The verdict is `better` or `worse` only when the chance of so uneven a split is at most 0.05, and `within noise` otherwise. A link to another skill that the judge gave the same relation as the user's choice is now counted apart, as "tied with yours". Re-scored from the stored judgments, with no new requests:

| Against | Method | Fixed | Broke | p | Verdict |
|---|---|---|---|---|---|
| `names` + `@2` | `names` + `@4` | 1 | 8 | 0.02 | worse |
| | `names` + `@5` | 0 | 4 | 0.06 | within noise |
| | `matched-trim@1` + `@2` | 0 | 5 | 0.03 | worse |
| | `matched-trim@1` + `@5` | 1 | 8 | 0.02 | worse |
| `names` + `@5` | `names` + `@4` | 1 | 4 | 0.19 | within noise |
| | `matched-trim@1` + `@5` | 1 | 4 | 0.19 | within noise |
| | `matched-trim@1` + `@4` | 1 | 6 | 0.06 | within noise |

`@5` was made the app's judge (`links=link-judge@5`) with the user's approval, as an exception to "adopt only when `better`". It is within noise of `@2`, and its figures aren't raised by examples taken from the reference set. The 4 links it loses are `C#` and `.NET`, which the user has overridden anyway, and two moves to an equally related skill. With `@5` as the base, no other measured method is better or worse beyond chance. Telling methods apart needs more reference links.

### Fourth round: a larger reference set and the CV line (2026-10-06)

The user merged a portfolio document into the profile (67 skills), deleted 34 near-duplicates and non-skills it
added (115 → 81 profile skills), and set 34 more links. The reference set grew to 46 links and 32 confirmed
refusals (16 left out as same identity). The merge's own weak spots, for `cv-atomic@1`: exact-match merging made
near-duplicates (`Postgres`/`PostgreSQL`, three `Jupyter` variants, eight phrasings of one research method),
paper titles and course names became skills, sections with other names were duplicated ("Selected Publications"
beside "Publications"), and 104 of 115 profile skills' evidence quote was only the skill's name.

`link-judge@6` is `@5` with each profile skill shown beside the CV line its evidence quote was found in (the
item's text, or the entry's title and organisation, cut to 200 characters around the quote) instead of the quote
alone. All against `names` + `@5`:

| Method | Right | Right skill added | Refusals kept | Fixed | Broke | Verdict |
|---|---|---|---|---|---|---|
| `names` + `@5` | 20 of 46 | 24 | 32 of 32 | | | |
| `names` + `@6` | 18 | 23 | 32 of 32 | 2 | 4 | within noise |
| `names` + `@2` | 22 | 28 | 32 of 32 | 3 | 1 | within noise |
| `matched-trim@1` + `@5` | 15 | 18 | 31 of 32 | 2 | 8 | within noise (p=0.05) |
| `skill-expand@1` + `@5` | 16 | 16 | 19 of 32 | 5 | 22 | worse |

**Nothing adopted; the app stays on `names` + `@5`.** What the figures show:

- **The CV line strengthens relations without making them more right.** `@6` fixed `C#` → `Java` and
  `agentic coding tools`, but called `agent frameworks` the same as `agentic AI workflows` and
  `Technical communication` specific to `Presenting technical material`.
- **The judge is stricter than the user on `general` and `related`.** By the user's relation, `@5` gets `same` 9 of
  9 and `specific` 4 of 8, but `general` 1 of 7 and `related` 6 of 22, and makes no link the user refused. The
  three list judges differ by a few posting skills each way, all within noise.
- **The largest single failure is now candidate finding: 11 of 46 right skills are not shortlisted.** Most link a
  concept to a tool whose name shares nothing with it (`Vector databases`, `Embeddings` → `ChromaDB`;
  `Document processing`, `LlamaIndex` → `Docling`; `Document classification` → `RAG pipeline`). Max-pair expansion
  ranks the right skill first for 4 of them, as D3 intended, but its hub phrasings again bring candidates into
  refusals: 13 broken.
- **Some refusals are stale, and some reference answers disagree with each other.** Four refusals were set before
  the merge added the skill expansion now links them to (`Embedding and Vector Search`, `Pinecone` → `ChromaDB`;
  `TensorFlow` → `Keras`; `LLMs` → `LangChain`): the user never saw those candidates. Pairs such as `C#` → `Java`
  (related) beside `Kotlin` (no link), or `Vector databases` → `ChromaDB` (specific) beside `Pinecone` (no link),
  can't both be matched by one rule. A refusal is a judgment against the profile of its day; nothing marks it for
  review when the profile grows.

**Re-scored after the user updated the stale refusals.** The user re-linked the four stale refusals and `Kotlin`
(→ `Java`, related, matching `C#`), so the reference set became 52 links and 27 refusals. 21 new judgments; the rest
reused:

| Method | Right | Shortlisted | Refusals kept | Fixed | Broke | Verdict |
|---|---|---|---|---|---|---|
| `names` + `@5` | 21 of 52 | 36 | 27 of 27 | | | |
| `names` + `@6` | 19 | 36 | 27 of 27 | 2 | 4 | within noise |
| `names` + `@2` | 23 | 36 | 27 of 27 | 3 | 1 | within noise |
| `matched-trim@1` + `@5` | 15 | 35 | 26 of 27 | 2 | 9 | worse |
| `skill-expand@1` + `@5` | 21 | 41 | 19 of 27 | 10 | 18 | within noise (p=0.09) |

Max-pair expansion moved from `worse` to `within noise`: the stale refusals had counted its right answers against
it. The 10 it fixes are the concept-to-tool links bare names can't find (`Vector databases`, `Pinecone`,
`Embedding and Vector Search` → `ChromaDB`; `TensorFlow` → `Keras`; `Document processing` → `Docling`; `C#`,
`Kotlin` → `Java`). Of the 18 it breaks, 8 are refusals (mostly `general` to a broad profile skill, such as
`fine-tuning` → `ML techniques`), 3 are degrees decided by shortlist order (`MEng` before `PhD` or `MSc`), and the
rest move to another plausible skill (`Data analysis` → `pandas`, `Large Language Models (LLMs)` → `Claude`).

### Decision at the end of the change (2026-10-06, with the user)

- **The app uses `names` + `link-judge@5`** (pipeline `links=link-judge@5`).
- **Kept for later measurement:** `skill-expand@1` + `@5`, whose concept-to-tool links are what bare names miss, and `names` + `@6`.
- **Deleted from the code:** `link-judge@2`, `@3` and `@4`, and `matched@1` and `matched-trim@1`, with the code only they used (D4). Their figures are above.
- **No rephrase checkbox** (D2). The backend that records the choice stays.
- **Follow-ups** go in `FUTURE_CHANGE.md`: a shortlist that adds expansion's best one or two candidates to the bare-name shortlist, flagging a confirmed refusal for review when a new profile skill becomes its candidate, `cv-atomic@1`'s merge weaknesses from the fourth round, and the posting skill's line for the judge.

## Risks / Trade-offs

- **[Generic phrasings match everything]** (a phrasing like "software development" lifts many pairs) → The prompt forbids broader skills, phrasings are capped at eight words, and the sweep's mean-candidate figure exposes it. A later expansion version can drop phrasings that match too many profile skills.
- **[More candidates mean more judge requests and more chances to over-link]** → Mean candidates and kept refusals are both reported, and the floor is set from the sweep.
- **[Small, hand-picked reference set]** (29 links and 21 refusals at first, 52 and 27 at the end) → The paired verdict says `within noise` unless a difference is unlikely by chance, and the table is read with the user. Before measuring, suggest adding the recurring unlinked skills the user hasn't labelled (LLMs, LLM APIs, Prompt engineering, Data analysis, data science, LLM evaluation, fine-tuning) to the reference set.
- **[Tuning to the reference set]** → Prompt examples never come from overrides (D5). The reference set keeps growing as the user links more.
- **[Automatic GPU work after an upgrade]** (one judgment per judged posting skill after a judge change, plus one expansion per skill when a method that expands is adopted) → It starts only at the first `serve` after the version change. It shows on the queue page and can be cancelled, and old links stay in effect throughout.
- **[A posting skill's first quote misleads its expansion forever]** → Rare. It's visible in the measurement's JSON. A new expansion step version re-expands everything.
- **[CPU time grows with profile × posting skills]** → About 6 s today. See Open Questions.

## Migration Plan

1. Copy `data/jobhunt.db` before migrating (CLAUDE.md, "Data and backups"). `0006` is additive.
2. Until adoption (task 6.4), the app's current method stays `names` + `link-judge@2`, so deploying the code changes nothing the user sees.
3. Adoption is a code change to `CURRENT_RETRIEVAL` / `CURRENT_JUDGE`. The next `serve` queues the re-judging pass (D4). Making `link-judge@5` current did this once.
4. Rollback: point the constants back (the superseded entries come back from git), and the next `serve` re-judges. Going below `0006` drops expansions, measurements and each merge's rephrase choice. CLAUDE.md's backup note says so.

## Open Questions

- **numpy for similarity.** If phrase-pair similarity gets slow as the profile and postings grow (D3), adding numpy is a dependency decision for the user. Nothing in the specs depends on it.
- **The floor and size for `skill-expand@1`** are still the starting 5 and 0.75. They would be chosen from the sweep if expansion is measured again with a view to adopting it (`FUTURE_CHANGE.md`).
