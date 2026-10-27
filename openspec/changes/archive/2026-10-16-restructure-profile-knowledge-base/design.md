## Context

See proposal.md for motivation. The current state that shapes the approach:

- **Tables.** The profile lives in `profile_sections`, `profile_entries`, `profile_items` and `skill_evidence` (evidence points at one entry or one item). A skill's level is `skills.level` / `level_origin`. `profile_deletions` holds fingerprints built from merge-matching keys. `profile_merges` / `profile_merge_changes` log each automatic merge for rollback. All of these are user-authored and written only by `userdata.py`.
- **Merging.** `jobs._run_document` stores a `document_runs` row (via `derived.save_document_run`) and calls `userdata.merge_run` in the same transaction, which queues link judging. The pipeline is `cvseg=caps@1 cvlines=llm@1 cvskills=cv-atomic@1 validate=v@3`, plus an optional ` rephrase` suffix.
- **Posting suggestions** are the pattern to follow. Verified items are derived rows (`enrichment_skills`), and rejections are user rows (`rejected_suggestions`). What is pending is computed when read, never stored. Accepting copies the item into a user row with origin `suggestion`.
- **Linking** reads `queries.profile_skills` (skills with a level), `queries.expansion_contexts` (the quote of the oldest evidence, or of the newest `rephrase` merge's evidence), and `queries.context_lines` (`link-judge@6` only). `link-judge@5` shows each candidate with its context quote. Re-judging is driven by shortlist, embedding model and pipeline changes, not by context changes.
- **The user's data** (read-only checks, 2026-10-13/15): 2 documents merged, 11 sections, 27 entries, 90 items, 336 skills (82 with a level: 74 `proficient`, 7 `expert`, 1 `familiar`; 81 set by the model), and 133 evidence rows (118 on items, 15 on entries; 14 with claimed years). There are 34 remembered deletions (all skills), 95 link overrides (27 "no link") and 174 stored expansions. Neither merge used `rephrase`. Every profile row has origin `model`.

## Goals / Non-Goals

**Goals:**
- One source of truth that `generate-tailored-cv` can query: facts (records), assertions (claims), vocabulary (skills) and wording (highlights), each changed only by the user or with the user's approval.
- An upgrade that loses nothing the user made: levels, the one user-set level, the 34 deletions and the 95 overrides.
- No change to link judging's input for existing data, so no new judge version, no GPU measurement and no re-judging are needed.
- Portable SQL only (SQLite and Postgres), and one writer per data kind as today.

**Non-Goals:**
- Anything listed under "Deferred to `generate-tailored-cv`" in proposal.md.
- Merging duplicate records automatically. The user rejects or deletes duplicates, and may merge their lines by hand.
- Measuring document extraction with an eval like `jobhunt eval`. The rebuild and the new extraction are compared by the user (D10).
- Suggesting profile details, or suggesting outcome records (an award line stays a description line unless the user makes it a record).

## Decisions

### D1. Tables

All new tables except `profile_suggestions` are user-authored, written only by `userdata.py` and listed in `db.USER_TABLES`. Dates are partial ISO text as today (`2022`, `2022-09`).

| Table | Columns | Notes |
|---|---|---|
| `records` | id, kind, title, organisation, location, start_date, end_date, ongoing, disclosure (`public`/`private`), part_of_id (FK records, nullable), context_lost_at (nullable), origin, source_run_id (FK document_runs, nullable), created_at, updated_at | `kind` in `userdata.RECORD_KINDS`. No `position` (D3). |
| `record_lines` | id, record_id, position, text, origin, created_at, updated_at | Ordered description lines; no dates. |
| `record_sources` | id, record_id, position, kind (`repo`/`site`/`doi`/`document`/`other`), url, document_id (FK documents), origin, created_at | Exactly one of url and document_id. |
| `claims` | id, skill_id (FK skills, UNIQUE), level, level_origin (`model`/`user`), origin, source_run_id, created_at, updated_at | The handoff called the level "strength". It is named `level` to match the scale used everywhere else (`SKILL_LEVELS`, the recommendations spec, the UI). |
| `claim_records` (grounds) | claim_id, record_id, quote, origin, created_at; PK (claim_id, record_id) | Quote kept (question H), so the judge's input is unchanged. |
| `highlights` | id, text, origin, source_run_id, created_at, updated_at | Listed in creation order. Their order on a CV belongs to change 2. |
| `highlight_claims` (coverage) | highlight_id, claim_id, quote (nullable), origin, created_at; PK (highlight_id, claim_id) | The quote and time preserve contexts for the 57 claims-section evidence rows (D9). |
| `skill_aliases` | alias_key (PK), skill_id (FK skills), created_at | `alias_key` is a `name_key`. |
| `profile_details` | id, kind (`name`/`headline`/`contact`/`summary`/`goal`), label, text, created_at, updated_at | Flat rows. The user preferred rows if the code is cleaner, and it is: every other user table has a `userdata` writer and per-row forms. |
| `profile_rejections` | id, kind, identity (UNIQUE), label, created_at | Replaces `profile_deletions` (D6). |
| `profile_suggestions` (derived) | id, run_id (FK document_runs), position, kind, payload_json | Written only by `enrich/derived.py`, never edited. |

`origin` is `user`, `suggestion` (accepted) or `model` (carried over from the old automatic merges). `source_run_id` records the run an accepted row came from. It stands in for merge history (question N): the profile page can show which document a row came from, and a bulk "remove everything from document X" can be added later if needed.

Dropped: `profile_sections`, `profile_entries`, `profile_items`, `skill_evidence`, `profile_deletions`, `profile_merges`, `profile_merge_changes`, `skills.level`, `skills.level_origin`.

### D2. `part_of` and disclosure

The guideline, written by the user, is quoted word for word here, in the `skill-profile` spec ("Record context"), on the record edit form and in the `part-of@1` prompt (D7):

> a `part_of_id` reference is made by a Record entry when the existing entry is missing important context, may be misinterpreted, or may be difficult to understand without also considering its linked Record entry

The user's worked examples:
- The **EXCONF 2024 paper is not** part of the PhD. It stands on its own, even though it came out of the PhD research.
- The **PhD thesis is** part of the PhD. A thesis makes no sense without the degree requirement.
- **tidyplots is** part of the EXCONF 2024 paper. It lacks important context without the paper.
- The hackathon's **"Best Design" award** would be part of city-parking, if it becomes its own record.

Further decisions:
- **When an outcome becomes a record** (question G): only when it has its own date, source or disclosure, or a claim would cite it. Otherwise it stays a description line. Terms taught qualify by their own dates (D4).
- **Cycles** are refused in `userdata.set_part_of` by walking the parent chain in Python. Chains are a few links long, so no recursive SQL is needed.
- **Deleting a context record** (question F) clears `part_of_id` on its dependents and sets `context_lost_at`. Setting a new link or "dismiss" clears the flag. The dependents are not deleted.
- **Effective disclosure** (question E) is computed in `queries`, never stored: a record is private if it or any ancestor is private. Change 2 must use the effective value. In this change it only affects how the profile page marks records.
- `part_of` never counts as grounds. Nothing in the claim queries follows `part_of_id`.

### D3. Record kinds and ordering

`RECORD_KINDS = ("role", "course", "project", "publication", "degree", "award", "event", "task", "other")` is a fixed tuple in `userdata.py`, like `SKILL_LEVELS` (question M). Records are sorted in Python (`queries.record_sort_key`) within each kind (question K):
1. ongoing first;
2. then by `end_date` (else `start_date`), newest first. Partial ISO strings compare correctly as text;
3. undated last;
4. ties by `id` (creation order).

There is no `position` column. Description lines keep `position`, because their order is part of the content.

### D4. One record per term taught

Course work is stored as one `course` record per term (question G, the user's direction). For example, there are three records for COMP 1000 at Example Polytechnic: Winter 2025, Winter 2026 and Fall 2026.

- **Grouping key convention:** term records of one course share kind, title and organisation, and differ only in their dates. Titles are kept as the source writes them ("Sessional Instructor, COMP 1000 Introduction to Programming"), not rewritten per term. Change 2 groups on (kind, title, organisation) to condense terms on the CV, either into "COMP 1000 at Example Polytechnic (2024–2026)" or into a short list of terms under one heading, as the user's own CV does. **Condensing is presentation, deferred to change 2**, and CLAUDE.md will say so.
- **Term months** (confirmed by the user): Winter = `YYYY-01`–`YYYY-04`, Summer = `YYYY-05`–`YYYY-08`, Fall = `YYYY-09`–`YYYY-12`. Durations then come out from record dates, and change 2 can print "Winter 2025" back from them.
- **The rule** (`enrich/terms.py`, pure Python, no model): a line matching `^Taught\s+` followed by one or more `(Winter|Summer|Fall)\s+\d{4}` separated by commas or "and". Anything else stays a description line. "Spring" and "Autumn" are not matched (neither appears in the user's documents). They can be added if a document uses them.
- **On the user's data** the rule turns 6 course entries into 10 records: one course taught in four terms, one in two, and four taught once. The "Lecturer (part-time)" role and its course-list lines stay as they are. The rebuild doesn't remove duplicates.

### D5. Aliases

- `userdata.merge_skill(merged_id, kept_id)` refuses the merge when `kept` has no claim or when the two are the same skill. It then:
  - moves the merged claim's grounds and coverage to the kept claim (skipping any it already has) and deletes the merged claim;
  - inserts `skill_aliases(merged.key → kept)`, and re-points aliases that pointed at `merged`;
  - re-points `skill_link_overrides.skill_id` from merged to kept;
  - forgets any rejection of the merged claim's identity, and queues link judging.

  Marks, `rejected_suggestions` and eval matching are untouched (handoff §2.2). The kept claim's level is unchanged.
- `queries.resolve_skill(conn, key)` returns the kept skill for an alias key, else the skill with that key. Its callers are claim suggestions (`profile_suggestions` claim identities), `set_skill_level` (a level set on an alias sets the kept claim), the level shown beside marks, and `effective_links` step 2.
- **Linking through aliases** (`skill-linking`, "Links to profile skills" step 2): a posting key that is an alias of a profile skill links `same` without a model request. The handoff kept posting marks and overrides keyed as now, and they are. This decision only extends "the profile resolves through aliases" to the same-identity check, because the user declared the two skills the same. As a side effect, an override on an alias key leaves `eval --links`' reference set ("has a same-identity profile skill"), and the report counts it under that reason.
  - *Alternative:* aliases only affect suggestions and levels, and linking ignores them. Not taken: the posting skill `Postgres` would then be judged against `PostgreSQL` by the model every time, after the user had already said they are the same.
- `skill_aliases` is user-authored. Removing an alias deletes the row only.

### D6. Suggestions, identities and rejections

**Storage.** A successful document run of the new pipeline writes one `profile_suggestions` row per verified suggestion. The `kind` is `record`, `claim`, `part_of` or `highlight`, and `payload_json` holds:
- a record: kind, title, organisation, location, dates, ongoing, lines, sources;
- a claim: skill name, level, grounds `[{record: <run-local position>, quote}]`, coverage `[{highlight: <position>, quote}]`;
- a `part_of` link: `{record, part_of}` as positions;
- a highlight: text.

Grounds and coverage refer to the run's own records and highlights by position. Unverified items stay in `output_json` only, as today.

**Identities** (`userdata.identity_*`, one module-level set of functions shared by suggestions, user rows and rejections), with names and text normalised by `name_key`:
- `record|kind|title|organisation|start|end`
- `line|<record identity>|text`
- `source|<record identity>|url-or-document`
- `claim|<resolved skill key>`
- `ground|<claim identity>|<record identity>`
- `part_of|<record identity>|<record identity>`
- `highlight|text`
- `cover|<highlight identity>|<claim identity>`
- `level|<claim identity>|level`

A user row's identity is computed from its current values, so editing a record's title changes the identity of its lines and grounds as well. That is intended: the old identities are remembered as rejected, so the run's suggestions for the old wording aren't offered back.

**What is offered** (`queries.profile_suggestions(conn)`, pure read):
1. Take each document's latest succeeded run that has suggestion rows. Runs from the old pipeline have none, so they offer nothing.
2. Resolve each suggestion's identities and its run-local references against the current profile.
3. Classify each suggestion as `new`, `adds` (what it would add to an existing row) or hidden, following the spec's "Offered suggestions". Grounds and coverage whose target doesn't exist yet are counted as `waiting`. Those whose target suggestion was rejected are dropped.
4. Merge suggestions with the same identity across documents. Remove anything whose identity is in `profile_rejections`.

The result is grouped by kind, in dependency order: records, claims, `part_of` links, highlights. Nothing about pending state is stored, so a new run, an acceptance or a deletion is reflected on the next read.

**Accepting and rejecting** (`userdata.accept_profile_suggestion(conn, suggestion_id, now)`, `reject_profile_suggestion`, `accept_all_profile_suggestions(conn, kind)`):
- Accepting re-computes the offer for that one suggestion, then copies what is offered, with `origin='suggestion'`, `level_origin='model'` and `source_run_id`.
- Rejecting inserts each offered identity (the suggestion's own when `new`, each addition's when `adds`) into `profile_rejections`.
- "Accept all" takes one snapshot of the offers of one kind, accepts them in order and returns the count. Suggestions it unlocks (for example grounds waiting for records) appear on the next read, as the spec requires.
- Any acceptance that touches claims, grounds or coverage calls `skills_changed`.

**Deletions are rejections.** Deleting a record, line, source, claim, ground, `part_of` link, highlight or coverage, and editing a row so its identity changes, inserts the old identity. Adding something by hand deletes a rejection with the same identity. Rejections have no reason column: unlike posting suggestions, nothing measures profile extraction by reason.

*Alternative:* store a pending/accepted/rejected state per suggestion row. Not taken: derived rows are never edited, and state per row would go out of date whenever the profile changes. The posting pattern (computed on read) already handles that.

### D7. The document pipeline version

Pipeline id: `cvseg=caps@1 cvlines=llm@1 cvrecords=rules@1 cvskills=cv-claims@1 cvpartof=part-of@1 validate=v@3`.

- `caps@1` and `llm@1` are kept as they are. Contact and summary sections produce no suggestions.
- `cvrecords=rules@1` (no model) builds records, lines, sources and highlights from the labelled lines (spec: "Records, lines and dates from documents"). This includes the term split (D4), single-URL items becoming sources (classified `repo` for github/gitlab, `doi` for doi.org or `/doi/`, else `site`), and taking dates from lines for undated records.
- `cvskills=cv-claims@1` is `cv-atomic@1`'s request with the claimed-years field removed. Kind stays in the schema to help the model, but isn't stored. Each verified skill attaches to the record or highlight holding its line. Same-skill items in a run are folded into one claim suggestion, with every ground and coverage, at the highest level.
- `cvpartof=part-of@1` makes one request per run. It numbers the run's records (kind, title, organisation, dates, first line) and asks, for each, the number of the record it is part of, or null. The system prompt contains the guideline word for word. Its two examples are invented (a conference talk part of the paper it presents, and a dataset part of the study that produced it), not taken from the user's records, following the project's rule that examples are never the user's own pairs. Answers are dropped when they point at the record itself or out of range, or make a cycle (the later answer in record order is dropped).
- `cv-atomic@1`, `cv.REPHRASE`, `merge_run`, `rollback_merge` and `merge_again` are deleted. A queued job naming the old pipeline fails with the existing "not available in this version" error, and the user re-queues it.
- `jobs._run_document` stores the run and its suggestions and finishes the job. It no longer calls a merge, and no longer queues link judging.

### D8. The rebuild (revision `0008_knowledge_base`)

The upgrade runs inside the Alembic revision, with the conversion code **frozen in the revision file** (including its own copy of the term rule), because migrations must not import application code that later changes. It reads the old tables with plain SQL, writes the new ones, then drops the old tables and columns with `batch_alter_table`. The mapping is the spec's "Upgrading an existing profile". Further details:

- **Timestamps.** Each ground and coverage keeps its evidence's `created_at`, and each record, line and highlight keeps its row's times. This is what keeps expansion contexts, and so `link-judge@5`'s input, unchanged (D9).
- **Course entries.** Evidence on a split course entry, or on its "Taught …" line, becomes a ground on every term record. The "Taught …" line itself is consumed by the split.
- **Line dates.** An entry without its own dates takes them from its items' dates. On the user's data that dates the role and four projects. Other item dates are dropped (lines have none), and the text is kept.
- **Contact section.** The first item becomes `name`, the rest `contact` with their labels. On the user's data that includes "PhD Computer Science" (the user's headline) and "March 2027" (the month the CV was current, not profile data). The user changes the first to `headline` and deletes the second by hand. Rules can't tell those lines from contact details.
- **Highlights.** Items outside entries in non-contact, non-summary sections become highlights: the 9 "Skills & Experience" lines, the 4 keyword-list lines (question J) and 3 section intros.
- **Expected result on the user's data:**
  - 31 records (21 entries kept, plus 10 term records) and 13 sources (7 repositories, 6 publication links);
  - 16 highlights with 65 coverages;
  - 82 claims: 43 ungrounded (claims backed only by claims lines or the keyword list), and the user's one level kept as `user`;
  - 68 evidence rows that become grounds, more after the term split;
  - 34 rejections and 12 details.

  The tests assert these proportions on a synthetic fixture, and the user checks the real numbers after upgrading.
- **Downgrade** recreates the old tables empty, restores `skills.level` / `level_origin` from claims, and turns claim rejections back into skill deletions. Records, highlights, details and aliases are lost. CLAUDE.md's backup note says to copy `data/` first.

### D9. Linking context

- `queries.expansion_contexts` returns, for each claim, the quote of the earliest of its grounds and coverages by `created_at`. Ties go to grounds first, then by record or highlight id. Coverage without a quote is skipped. The `profile_merges.rephrase` branch is removed.
- `queries.context_lines` (`link-judge@6`) returns the record line containing the quote (else the record's title and organisation) for a ground, and the highlight's text for coverage.
- For rebuilt data, every claim's earliest ground or coverage is its former oldest evidence with the same quote. So `link-judge@5` requests are byte-identical, and the shortlists (name embeddings of the same profile skills) are unchanged. Nothing is re-judged by the upgrade. A test compares `expansion_contexts` before and after upgrading a fixture.
- `skill-expand@1` and `link-judge@6` stay registered for measuring (question O) and read the new contexts. The `rephrase` flag, `enqueue_document(rephrase=)`, `profile_merges.rephrase` and the spec text about it are removed.

### D10. Comparing the rebuild with a new extraction

The user wants both results and to choose between them. `jobhunt profile reset --db URL --yes` (in `cli.py`, calling `userdata.reset_knowledge_base`) makes the clean copy:

```
  back up data/  -->  upgrade data/jobhunt.db (= rebuild, "A")
                          |
                          +--> cp to scratch B --> profile reset --yes --db B
                                                   serve --db B: "Add to profile" on both documents
                                                   (GPU: confirmed with the user before each run)
                                                   review suggestions in B
  compare A and B:
    - duplicates and non-skills among claims, and duplicate records (by inspection, with the profile counts)
    - grounds on the right records (spot-check ~15 claims, Python, Flask and Django among them)
    - jobhunt eval --links --db A, then --db B (GPU, confirmed first), verdict B vs A
    - link overrides gone stale in each (the links page states the count)
  choose: keep A; or, if nothing else changed in A meanwhile, replace data/jobhunt.db with B
```

The reset keeps rejections, aliases, details and overrides, so B honours the 34 carried-over rejections (handoff §4.2b). Going stale (question D) is acceptable: stale overrides are already shown as stale and ignored, and their count is one of the criteria. The links page gains a count of stale overrides for this.

### D11. Web interface

- `/profile` is rewritten. It holds the details panel, records grouped by kind (in `RECORD_KINDS` order, each record with its lines, sources, disclosure, part-of and dependents, and lost-context flag), claims grouped by level (grounds, highlights, aliases, ungrounded and no-highlight flags, linked posting skills as today), highlights, counts, and links to suggestions and rejections. Editing uses small forms in `<details>`, posting with a 303 back to an anchor, as today.
- `/profile/suggestions` lists the four groups with "Accept all (n)" and per-item accept and reject (htmx swaps the group).
- `/profile/rejections` replaces `/profile/history`, listing rejections with "forget".
- `/profile/links` is unchanged, apart from the stale-override count.
- Route modules stay thin: logic goes in `userdata.py` and `queries.py`.
- Wherever a level is shown or set (posting marks, `/skills`, Insights, the posting summary), the claim's level is read through `queries` with alias resolution. `recommend.py` keeps reading `queries.profile_skills`, which now joins `claims`.

## Risks / Trade-offs

- [The model words the same record differently on two runs or in two documents, so identities differ and duplicates are offered] → Duplicates are rejected once and stay rejected. The comparison (D10) counts them. Merging records is left out of this change on purpose.
- [43 of 82 claims are ungrounded after the rebuild] → This is the honest state of the data (they were backed only by assertions). The profile page flags them and counts them, and suggestions or hand edits ground them.
- [A lossy downgrade] → CLAUDE.md and the task list say to back up `data/` before upgrading. The downgrade keeps levels and skill rejections, which are what posting pages and Insights need.
- [A large migration with frozen logic duplicated from `terms.py`] → Tests run the upgrade on a synthetic 0007 database covering every mapping rule. `test_migrate.py` keeps checking the schema matches `db.metadata`.
- [The term rule misses a format the user writes later] → It only matches the strict "Taught <Term> <Year>, …" form, and anything else stays a line. The record can be split by hand.
- ["Accept all" lets model mistakes in] → Accepted rows stay marked model-derived, and deleting one remembers it as rejected.
- [Aliases change `same` links and the `eval --links` reference set] → Only for alias keys, which the user creates deliberately. The report already lists overrides left out by reason.
- [Private records reach the local model in judging requests (their grounds' quotes)] → Everything stays on the machine (Ollama only). Non-disclosure is about rendered CVs, which change 2 enforces.

## Migration Plan

1. Back up `data/` (database and documents).
2. Run `jobhunt serve` or `jobhunt import` with the new code. `init_db` applies `0008_knowledge_base`.
3. Check the profile page's counts against D8's expected numbers. Change the headline detail and delete the "March 2027" detail.
4. Optionally run the comparison (D10) and choose A or B.
5. Rollback: restore the backup. `alembic downgrade 0007_run_origin` restores levels and skill rejections only.

## Comparison results

Run on 2026-10-16. A is `data/jobhunt.db` after `0008_knowledge_base`. B is a reset copy with both documents extracted by the new pipeline (gemma4:12b; 66 s and 135 s), and every suggestion then accepted with "Accept all" in a further copy (`compare-B-all.db`), so B shows the raw extraction.

**The upgrade (A)** matched D8: 31 records (10 courses), 13 sources, 16 highlights with 65 coverages, 82 claims (43 ungrounded, the user's level kept as `user`), 34 rejections and 12 details. It has 59 grounds rather than "68 evidence rows". Nothing was lost: the 68 rows cover 58 distinct (skill, entry) pairs, and the term split adds one.

**B's runs** stored 8 + 23 records, 49 + 80 claims, 9 + 7 highlights and 1 `part_of` link. Offered after merging across documents and removing the 34 rejections: 31 records, 86 claims and 16 highlights. The `part_of` link waited for its records, as specified.

| | A (rebuild) | B (new extraction) |
|---|---|---|
| Records / lines / sources | 31 / 43 / 13 | 31 / 44 / 13, the same records |
| `part_of` links | 0 | 1: tidyplots → the EXCONF 2024 paper (the user's own worked example) |
| Claims (ungrounded, no highlight) | 82 (43, 28) | 86 (46, 31) |
| Claims in one only | Communication, Mentoring, PhD in computer science, Presenting technical material, Technical writing, assessment design | an event name, a paper-title fragment, evaluating benchmark performance, team management, communicating difficult ideas, Curriculum design & instruction, Constrained & numerical optimization, Applied Optimization Track, Peer-reviewed technical writing, Presenting technical material to mixed audiences |
| Grounds | 59 | 57; same ground sets for 35 claims (Python, Flask and Django among them); B loses the course grounds of `computer science` and `operating systems` |
| Stale link overrides | 0 | 5 (3 to Communication, 2 to Mentoring) |
| `eval --links`: reference links / right / refusals kept | 50 / 18 / 27 of 27 | 47 / 18 / 24 of 27 |

`eval --links`, paired by posting skill: B fixes 2 (`advanced degree`, `master's degree`) and breaks 3 refusals (`ai evaluation`, `evaluation frameworks` and `testing` now link to B's `evaluating benchmark performance`), so the result is within noise. B's extra claims are mostly what `FUTURE_CHANGE.md` §3C describes: an event name, a paper-title fragment and long phrasings of existing skills.

**Choice: A.** `data/jobhunt.db` stays as upgraded. The user adds the tidyplots → EXCONF 2024 context link by hand. `data/compare-B.db` and `data/compare-B-all.db` are kept for reference.

## Open Questions

- Should the profile page show a claim's span of years worked out from its grounding records' dates? It's cheap, but its meaning ("N+ years") is the CV's concern. Left to change 2 unless the user wants it sooner.
- Should a later `part-of` version also suggest links to records already in the profile, not only within one run? That waits until the user has used `part-of@1`.
