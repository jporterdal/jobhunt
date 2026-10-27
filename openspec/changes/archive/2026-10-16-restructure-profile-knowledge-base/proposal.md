## Why

The user wants to generate a CV for each target job by choosing and ordering facts, with their evidence, by relevance to the posting. Today's profile can't support that. It mirrors the layout of the documents it was read from (sections, entries, items), so the same work appears under several headings: two `claims`, two `experience` and two `publication` sections after two documents. A skill's level sits on the shared `skills` row. Evidence points at whatever line named the skill, so a project that shows Python and a CV bullet that only asserts it count the same. And every document run is merged automatically, so the user has never approved a single row: all 27 entries, 90 items and 133 pieces of evidence are model-made, and the user has had to delete 34 near-duplicate or non-skill skills by hand.

This change turns the profile into a knowledge base that CV generation can query. **A second change, `generate-tailored-cv`, is expected to follow**, and builds on the structure defined here (see "Deferred to `generate-tailored-cv`" below).

## What Changes

- **Four layers replace sections, entries, items and evidence. BREAKING (schema and pages):**
  - **Records** are facts: roles, courses taught, projects, publications, degrees, awards, events, tasks. Records are flat, with one optional `part_of` reference to the record that gives them context. Each has dates, ordered description lines, a list of sources (repository, site, DOI, uploaded document) and a disclosure, `public` or `private`. Dates live on records only.
  - **Claims**: one per skill, holding the user's level on the existing scale (`missing` … `expert`). Claims are the only link from records to skills, grounded by any number of records, each ground with the quote that names the skill. A claim with no grounds is allowed and flagged as ungrounded, except at `missing`.
  - **Skills** stay the vocabulary shared with posting marks. They gain **aliases**: merging one skill into another makes the first an alias of the second, on the profile side only.
  - **Highlights** are the wording the CV prints. Each covers one or more claims.
  - **Profile details** (name, headline, contact details, summaries and goal statements) are flat rows, edited by hand, outside the chain.
- **The level moves from `skills` to the claim. BREAKING (schema).** "In the profile" now means "has a claim". Setting a level anywhere (posting page, skills page, Insights) creates or updates the claim, and clearing it removes the claim.
- **Document runs suggest; the user decides. BREAKING (behaviour):** a document run no longer merges into the profile. It stores suggestions of four kinds (records with their lines and sources; claims with their level and grounds; `part_of` links; highlights with the claims they cover), which the user accepts or rejects one at a time, or with "Accept all" for each kind across all documents. Accepted rows are copied into the user's tables, marked as from a suggestion. Rejections and deletions are remembered so they aren't suggested again, replacing remembered deletions.
- **Removed:** automatic merging, merge history, rollback and "merge again", the "rewrite phrasings" choice on document jobs, `skills.level`/`level_origin`, and the tables `profile_sections`, `profile_entries`, `profile_items`, `skill_evidence`, `profile_deletions`, `profile_merges`, `profile_merge_changes`.
- **A new document pipeline version** produces the suggestions, including `part_of` links judged under the user's guideline (quoted in design.md), and records split by rule from "Taught Fall 2026, Winter 2026, …" lines, one record per term.
- **Migration rebuilds today's profile** into the new tables (design.md, "Rebuild"): entries become records, course entries are split into one record per term, URL lines become sources, lines outside entries become highlights, levels become claims, evidence becomes grounds or highlight coverage, contact and summary lines become profile details, and the 34 deleted skills become remembered rejections. Link overrides keep pointing at the same skills.
- **Comparing rebuild and new extraction:** a `jobhunt profile reset` command clears the knowledge base of a database copy (keeping rejections, aliases, details and link overrides), so the new extraction can be run on a clean copy and browsed beside the rebuilt one.
- **Linking keeps its input:** the judge sees each profile skill with the quote of its oldest ground or highlight coverage, which for rebuilt data is the quote it sees today. So `link-judge@5` needs no new version and nothing is judged again. A posting skill whose identity is an alias of a profile skill links `same` without a model request.

### Deferred to `generate-tailored-cv`

- Ranking claims and records for a posting (importance × relation × level), with grounding records chosen by co-grounding with the posting's other skills.
- Choosing highlights (a weighted set cover within a length budget), drafting new highlight wording with the model, and adding accepted drafts to the library.
- Checks on highlights: naming a skill none of its claims is about, overstating a claim's level, flagging for review when a covered claim changes.
- Rendering: never showing private records or anything that reveals them; showing a dependent record with its context; grouping headings by record kind; **condensing repeated records** (for example several terms of the same course into "COMP 1000 at Example Polytechnic (2024–2026)" or a list of terms under one heading); printing the month the CV was produced; the output format.
- A generated keyword list, which needs a `category` on claims; a skill `kind` for weighting.
- Whether description lines are always printed or chosen per job.
- Storing each application's CV (the chosen records and highlights, in order).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `skill-profile`: rewritten around records, claims, grounds, highlights, aliases, profile details, disclosure and `part_of`; editing and remembered rejections replace sections, entries, items, evidence and remembered deletions.
- `profile-extraction`: document runs store suggestions instead of merging; accepting, rejecting and "Accept all"; the new pipeline's records, terms, claims, `part_of` links and highlights; merge history and rollback removed.
- `skill-linking`: "profile skill" means a skill with a claim; aliases count as the same identity; the context shown to the judge and used for expansion comes from grounds and highlight coverage; the re-judging triggers follow the new profile actions; the "rewrite phrasings" choice is removed.
- `posting-triage`: a skill's level is its claim's level; setting or clearing it creates or removes the claim; accepting document suggestions replaces document merges in the user-authored rules.
- `llm-connection`: a document extraction no longer queues link judging by itself (accepting its suggestions does).

## Impact

- **Schema:** Alembic revision `0008` adds the new user-authored and derived tables, rebuilds today's data into them, and drops the old profile tables and `skills.level`/`level_origin`. Its downgrade restores levels and skill rejections only. The user should back up `data/` first.
- **Code:** `db.py` (tables and table-kind lists); `userdata.py` (records, lines, sources, claims, grounds, highlights, aliases, details, suggestions, rejections; replaces the profile editing, fingerprint and merge code); `queries.py` (`profile`, `profile_skills`, levels, suggestions, `expansion_contexts`, `context_lines`, `effective_links` with aliases); `enrich/cv.py` (the new pipeline version), `enrich/derived.py` (stores suggestions), `enrich/jobs.py` (no merge; triggers), `enrich/links.py` and `enrich/expand.py` (contexts); `recommend.py` (only through `queries`); `cli.py` (`profile reset`); `web/profile.py`, `web/triage.py`, `web/postings.py` and their templates.
- **Tests:** `test_profile.py`, `test_profile_jobs.py`, `test_cv_pipeline.py`, `test_web_profile.py`, `test_migrate.py`, `test_links.py`, `test_expand.py`, `test_link_eval.py`, `test_recommend.py`, `test_userdata.py`, plus tests for the rebuild against a copy of the 0007 schema.
- **Model use:** running the new pipeline over the two documents uses the GPU. The user has approved this in principle; each run is confirmed with the user first.
- **Docs:** CLAUDE.md (architecture, data kinds, profile section, backups and downgrade notes); `FUTURE_CHANGE.md` §3C (largely addressed here), updated during implementation.
- No new dependency.
