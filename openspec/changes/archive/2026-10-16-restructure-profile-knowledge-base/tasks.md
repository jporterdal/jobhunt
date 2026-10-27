## 1. Schema

- [x] 1.1 Add the tables from design D1 to `db.py` (`records`, `record_lines`, `record_sources`, `claims`, `claim_records`, `highlights`, `highlight_claims`, `skill_aliases`, `profile_details`, `profile_rejections`, `profile_suggestions`), remove the old profile tables and `skills.level`/`level_origin`, and update `USER_TABLES` / `DERIVED_TABLES`; verify `tests/test_migrate.py`'s table-kind checks list every new table in exactly one kind
- [x] 1.2 Add `userdata.RECORD_KINDS`, `DETAIL_KINDS`, `SOURCE_KINDS` and the `identity_*` functions from design D6, with docstrings; verify unit tests in `tests/test_userdata.py` show equal identities for names differing only in case and whitespace, and that a record's line, source and ground identities change with its title
- [x] 1.3 Add `enrich/terms.py` (the "Taught <Term> <Year>, …" rule, term to month range) as pure Python; verify `tests/test_terms.py` covers "Taught Fall 2026, Winter 2026, Winter 2025, Winter 2024" (four terms with the right months), "Taught Summer 2017 and Summer 2016", and non-matching lines ("Taught core courses", "Spring 2020")

## 2. Upgrade (revision `0008_knowledge_base`)

- [x] 2.1 Build a synthetic 0007-schema fixture in `tests/` that covers every mapping rule in the `skill-profile` "Upgrading an existing profile" requirement: a course entry with a multi-term "Taught" line and evidence on it, a project with a URL item and dated status line, a role with dated course-list items, claims-section and keyword-list items with evidence, a section intro, contact and summary sections (one named "Statement Of Goals"), a user-set level, skill deletions and a link override; verify the fixture loads at revision 0007 in a test
- [x] 2.2 Write `0008_knowledge_base` with the conversion frozen in the revision file (design D8): records (term split, dates from lines), lines, sources (kind by URL), highlights, coverage and grounds keeping evidence `created_at`, claims keeping level origin, details, skill deletions as claim rejections, then drop the old tables and columns with `batch_alter_table`; verify a new `tests/test_upgrade_profile.py` asserts each upgrade scenario in the `skill-profile` delta against the fixture
- [x] 2.3 Write `downgrade()` (recreate the old tables empty, restore levels and skill deletions from claims and claim rejections); verify a test upgrades and downgrades the fixture and finds the same levels and deletions
- [x] 2.4 Verify `pytest tests/test_migrate.py` passes on SQLite and with `JOBHUNT_TEST_PG_URL` set (the schema equals `db.metadata` at head)

## 3. Writing the knowledge base (`userdata.py`)

- [x] 3.1 Records, lines and sources: add, edit, delete, move lines; deleting a record deletes its lines, sources and grounds and flags its dependents (`context_lost_at`, `part_of_id` cleared); verify tests for each `skill-profile` "Records" and "Editing the knowledge base" scenario
- [x] 3.2 `set_part_of` (refusing self and cycles), `dismiss_lost_context` and `set_disclosure`; verify tests for "Thesis part of the degree", "Cycle refused" and "Deleting a context record"
- [x] 3.3 Claims: rewrite `set_skill_level`, `add_profile_skill`, `remove_profile_skill` and `rename_skill` on `claims`, resolving aliases; removing a claim removes its grounds and coverage and keeps highlights; verify tests for "Adding a skill by hand", "Removing a skill keeps posting marks and highlights" and `posting-triage` "Setting a level"
- [x] 3.4 Grounds and coverage: add (a hand-made ground's quote defaults to the record's title and organisation) and remove; highlights: add, edit, delete; each change that affects claims calls `skills_changed`; verify tests for the "Grounds" and "Highlights" scenarios and that each action queues one links job
- [x] 3.5 `merge_skill` and `remove_alias` (design D5: move grounds and coverage, re-point aliases and link overrides, forget the merged claim's rejection); verify tests for "Merging a near-duplicate", "Level set on an alias", "Posting marks stay as they are", an alias of an alias, and refusal without a kept claim
- [x] 3.6 Profile details: add, edit, delete; verify a test for "Headline and contact details"
- [x] 3.7 Rejections: each delete, and each edit that changes an identity, remembers the old identity; adding by hand forgets a matching rejection; `forget_rejection`; verify tests for the "Remembered rejections" scenarios
- [x] 3.8 Delete the section, entry, item, evidence, fingerprint and merge code (`merge_run`, `rollback_merge`, `merge_again`, `_MergeLog` and the rest); verify `grep` finds no references to the removed tables in `src/`

## 4. Reading the knowledge base (`queries.py`)

- [x] 4.1 `profile(conn)`: details in kind order, records grouped by kind and sorted by `record_sort_key` (design D3), each with lines, sources, effective disclosure, part-of, dependents and lost-context flag; claims by level with grounds, coverage, aliases and the ungrounded and no-highlight flags; highlights; counts; verify tests for the "Records" ordering scenarios, "Private through context", "Ungrounded claim", "Missing is never ungrounded" and "Claim without a highlight"
- [x] 4.2 `profile_skills` and every level read (skills page, marks, posting summary, Insights) through claims, with `resolve_skill` for aliases; verify `tests/test_recommend.py` passes unchanged apart from fixtures that set levels, and a test for `posting-triage` "Level of an alias"
- [x] 4.3 `effective_links` step 2 resolves alias keys; verify a test for `skill-linking` "Alias" (no judgment needed)
- [x] 4.4 `expansion_contexts` and `context_lines` from grounds and coverage (design D9), removing the `rephrase` branch; verify tests for each "Expansion context from grounds and highlights" scenario, plus a test that `expansion_contexts` gives the same quote per skill before and after upgrading the 2.1 fixture
- [x] 4.5 Add a stale-override count to the links page's data; verify a test with one stale and one live override

## 5. The document pipeline

- [x] 5.1 `cvrecords=rules@1` in `enrich/cv.py`: records, lines, sources and highlights from the labelled lines, the term split via `terms.py`, dates from lines for undated records, nothing from contact and summary sections; verify `tests/test_cv_pipeline.py` with the `profile-extraction` scenarios "Degree with a tab-aligned year", "Terms split by rule", "Project address becomes a source", "Claims lines become highlights", "Unverified date" and "Contact block"
- [x] 5.2 `cvskills=cv-claims@1` (claimed years removed), attaching each verified skill to its record or highlight and folding repeats; verify `FakeLLM` tests for "Claim with libraries", "Skill on a project line", "Wording sets the level" and "Invented skill quote"
- [x] 5.3 `cvpartof=part-of@1` with the guideline word for word and invented examples (design D7), dropping self, out-of-range and cyclic answers; verify `FakeLLM` tests for "Thesis and degree" and "Cycle dropped", and a test that the system prompt contains the guideline text exactly
- [x] 5.4 New `pipeline_id()`; delete `cv-atomic@1` and `REPHRASE`; `derived.save_document_run` stores `profile_suggestions` rows; `jobs._run_document` no longer merges or queues link judging; `enqueue_document` loses `rephrase`; verify `tests/test_profile_jobs.py` for `llm-connection` "Document extraction alone", "Mixed kinds in order", a failed run storing no suggestions, and a queued job with the old pipeline failing with the version error

## 6. Suggestions

- [x] 6.1 `queries.profile_suggestions(conn)` (design D6: latest succeeded run per document, identities, `new`/`adds`/hidden, waiting and dropped references, merged across documents, rejections removed, grouped in dependency order); verify tests for every "Matching suggestions" and "Offered suggestions" scenario
- [x] 6.2 `userdata.accept_profile_suggestion`, `reject_profile_suggestion` and `accept_all_profile_suggestions(kind)`; verify tests for "Accepting a claim", "Rejecting a non-skill", "Accepting all records" (count, and unlocked grounds offered afterwards, not accepted), `skill-linking` "Accepting a claim suggestion", and `posting-triage` "Document suggestion after triage"

## 7. Web interface

- [x] 7.1 Rewrite `/profile` (`web/profile.py`, `profile/profile.html`, `_macros.html`) per design D11, with every editing action of "Editing the knowledge base" and the guideline text on the part-of form; verify `tests/test_web_profile.py` renders each group and flag and posts each action (303 back to its anchor)
- [x] 7.2 Add `/profile/suggestions` with the four groups, "Accept all (n)" and per-item accept and reject; verify web tests for accepting, rejecting, "Accept all" and "Nothing to review"
- [x] 7.3 Replace `/profile/history` with `/profile/rejections` (list and forget); show the stale-override count on `/profile/links`; verify web tests for both
- [x] 7.4 Update the level controls and displays on postings, `/skills` and Insights to the claim reads, and remove the "rewrite phrasings" plumbing from the documents UI; verify `tests/test_web.py` and `tests/test_web_llm.py` pass
- [x] 7.5 In the running app (`jobhunt serve --db` on an upgraded copy of the fixture or real data), add a record, ground a claim, merge two skills, set a part-of link and accept a suggestion; verify each change shows on `/profile` without errors

## 8. Reset command

- [x] 8.1 Add `userdata.reset_knowledge_base` and `jobhunt profile reset --db URL --yes`; verify `tests/test_cli_*` for "Resetting a copy" (counts reported, details, aliases, rejections and overrides kept) and "No confirmation"

## 9. Linking and measurement

- [x] 9.1 Check `enrich/links.py`, `enrich/expand.py` and `enrich/link_eval.py` against the new `profile_skills`, contexts and aliases; verify `tests/test_links.py`, `tests/test_expand.py` and `tests/test_link_eval.py` pass, including a reference-set test where an override on an alias key is left out as same-identity

## 10. Wrap-up

- [x] 10.1 Run `pytest`, and again with `JOBHUNT_TEST_PG_URL` set; verify everything passes on both
- [x] 10.2 Update CLAUDE.md: project status, Architecture (`terms.py`, `cv.py`, `userdata.py`, `queries.py`, `derived.py`, `jobs.py`), the four data kinds' table lists, "The profile and skill links" (records, claims, grounds, highlights, aliases, details, suggestions, rejections; condensing term records is the CV's job, in `generate-tailored-cv`), Commands (`jobhunt profile reset`), and the backup and downgrade notes for `0008_knowledge_base`; verify the text matches what was built
- [x] 10.3 Update `FUTURE_CHANGE.md` §3C (cv-atomic@1 merge weaknesses) to say what this change addressed and what remains, and §2's "you have it, your CV doesn't say so" to point at claims without a highlight; verify by reading both sections
- [x] 10.4 When archiving, update the Purpose of `openspec/specs/skill-profile/spec.md` and `openspec/specs/profile-extraction/spec.md` (both still describe sections and automatic merging); verify `openspec validate --specs` passes

## 11. Moving the user's data (with the user)

- [x] 11.1 Ask the user to back up `data/`, then upgrade the real database; verify the profile page's counts against design D8's expected figures and report any difference to the user
- [x] 11.2 Make the comparison copy B (design D10: copy, `jobhunt profile reset --yes --db B`), then, **after confirming with the user**, queue extraction of both documents in B on the GPU; verify both runs succeed and their suggestions appear on B's suggestions page
- [x] 11.3 With the user, compare A and B on the D10 criteria (running `jobhunt eval --links` on each only **after confirming GPU use**), record the figures and the user's choice in this design ("Comparison results"), and adopt A or B; verify the chosen database is at `data/jobhunt.db`
- [x] 11.4 Once `generate-tailored-cv` is proposed, fold anything still relevant from `HANDOFF.md` into it and delete `HANDOFF.md`; verify the file is gone and nothing in it is lost
