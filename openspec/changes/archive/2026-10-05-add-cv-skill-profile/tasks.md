## 0. Prerequisites

- [x] 0.1 Confirm the starting point: the Alembic head is `0004_feedback`, no other change in `openspec/changes/` modifies `skill-profile`, `profile-extraction`, `skill-linking`, `posting-triage`, `application-tracking` or `llm-connection`, and `pytest` passes before any edit. Verify with `alembic history`, `openspec list`, and a passing `pytest` run. If any differ, stop and tell the user.
- [x] 0.2 Copy `data/jobhunt.db` to `data/jobhunt.pre-0005.db` before anything migrates the real database (CLAUDE.md, "Data and backups"). Verify that the copy exists and that `sqlite3` opens it read-only.

## 1. Schema (D2, D3, D6, D7, D8, D9, D10, D11)

- [x] 1.1 In `db.py`, add:
  - the profile tables: `profile_sections`, `profile_entries`, `profile_items`, `skill_evidence`, `profile_deletions`, `profile_merges`, `profile_merge_changes`, `skill_link_overrides`
  - `skills.level_origin`
  - the derived tables: `document_runs`, `skill_embeddings`, `link_judgments`, `link_relations`
  - the `llm_jobs` changes: `kind`, nullable `job_id` and `snapshot_id`, `document_id`, `document_run_id`.
  
  Add the new tables to `USER_TABLES` or `DERIVED_TABLES`, with comments in the style of the existing ones. Verify that `python -c "import jobhunt.db"` succeeds and that each new table is in exactly one of the table lists.
- [x] 1.2 Generate migration `0005_profile` against a scratch database at head (CLAUDE.md, "Schema migrations"). `upgrade()` maps the level `have` to `proficient` and sets `kind='posting'` on existing jobs. `downgrade()` deletes non-posting jobs, restores the `NOT NULL` columns, maps `familiar`, `proficient` and `expert` to `have`, and drops the new tables. Verify with `pytest tests/test_migrate.py` on SQLite and Postgres, plus a migration test that a `have` level becomes `proficient` and an existing job becomes `kind='posting'`.

## 2. ODT text (D4)

- [x] 2.1 `documents.extract_text` reads `.odt`:
  - one line per paragraph, heading, list item and table-cell paragraph, in document order
  - `\t` for tab stops, spaces for `text:s`, newlines for line breaks
  - text boxes read in place
  - images, tracked changes and annotations skipped.
  
  Build ODT fixtures in test code. Verify with `tests/test_documents.py` cases for the spec scenario "ODT with tab-aligned dates", a tracked change and an annotation producing no text, and a broken zip giving `failed: ...` while the upload succeeds.

## 3. Profile user data (D2, D3, D7)

- [x] 3.1 `userdata.SKILL_LEVELS` becomes the five-level scale, and `set_skill_level` records `level_origin='user'`. Clearing a level removes the skill's evidence and records a deletion. Verify with userdata tests: each level, refusal of `have`, clearing removing the evidence and leaving marks unchanged ("Removing a skill keeps posting marks").
- [x] 3.2 Profile writes in `userdata`:
  - add, edit and delete for sections, entries, items and evidence
  - move up and down within the parent
  - change a section's kind.
  
  Content edits set `origin='user'`. Moves don't change origin. Deleting a section or entry removes its children and any evidence pointing at them. Every deletion records a `profile_deletions` fingerprint (D7), and a "forget" removes one. Verify with userdata tests on SQLite and Postgres matching "Editing a model-made bullet", "Reordering keeps origin", "Deleting an entry" and "Changing a section's kind".
- [x] 3.3 `queries.profile(conn)`: sections in order with their entries and items, and profile skills grouped by level, each with its evidence and target rows. Verify with a query test on a profile built through `userdata` covering an item directly under a section, an entry's dated items, and an ongoing entry.

## 4. Document pipeline (D5)

- [x] 4.1 The `caps@1` section step and contact rules:
  - heading detection on the text before the first tab
  - the ordered keyword map for kinds, with lines before the first heading becoming `contact`
  - email, URL and phone patterns, with the first line as the name.
  
  No model involved. Verify with unit tests matching "Heading with a tabbed note", "Combined heading" and "Contact block". The last checks that a `FakeLLM` receives no contact text.
- [x] 4.2 The `llm@1` line labeller: numbered lines per section, labels `entry`, `bullet`, `detail` or `text`, field and date quotes, and text left on an entry's line becoming its first item. Its schema's top-level field is `lines`. Verify with `FakeLLM` tests matching "Degree with a tab-aligned year" and "Continuation lines".
- [x] 4.3 The `cv-atomic@1` skill step: one call per section that can hold evidence, with `name`, `kind`, `quote`, `years` and `level`, retrying once on an empty result. Its top-level field is `cv_skills`. Verify with `FakeLLM` tests matching "Claim with libraries and years" and "Wording sets the level", and that `summary` and `contact` sections are never sent.
- [x] 4.4 Validation and run assembly:
  - field, date and skill quotes are located with `validate.locate`
  - dates are parsed to partial ISO, or flagged as ongoing
  - `years` is kept only when it appears in the line
  - verified results are put in the run structure, and unverified ones in the trace
  - the pipeline id is `cvseg=caps@1 cvlines=llm@1 cvskills=cv-atomic@1 validate=v@3`.
  
  Verify with tests matching "Unverified date", "Unverified years" and "Invented skill quote".
- [x] 4.5 `derived.save_document_run` stores runs (succeeded or failed) and never edits them. Verify with tests matching "Extracting twice" and "Failed run" (the profile is unchanged).

## 5. Merge and rollback (D6, D7)

- [x] 5.1 `userdata.merge_run(conn, run_id)`, following D6's matching rules:
  - empty fields are filled only on model-made entries
  - new rows are appended
  - model levels are raised to the higher suggestion
  - user rows, user levels and deleted fingerprints are left alone
  - every insert and fill is logged in `profile_merges` and `profile_merge_changes`.
  
  Verify with userdata tests matching "First CV", "Second document overlaps the first", "User level kept", "Model level raised", "User edit survives a merge", "Deleted entry stays deleted" and "Document merge after triage".
- [x] 5.2 `userdata.rollback_merge` and "merge again": changes are walked in reverse, only rows unchanged since the merge are removed or emptied, and the rows kept are returned. Verify with tests matching "Rolling back a merge", "Merging again" and "Forgetting a deletion".

## 6. Embeddings and settings (D9)

- [x] 6.1 `OllamaClient.embed(model, texts)` calls `/api/embed` in batches, and fails the step when the vector count doesn't match. `FakeOllama` gains a deterministic character-trigram `embed`. Verify with `tests/test_ollama.py` against the stdlib stub, including "Short embedding response".
- [x] 6.2 Add the `llm.embed_model` setting: it defaults to an installed `nomic-embed-text`, only models with the `embedding` capability are offered, and it's validated in `set_setting`. Verify with userdata and web tests matching "Choosing an embedding model", and that the chat-model choices still exclude embedding models ("Choosing a model").

## 7. Linking (D8, D9, D10)

- [x] 7.1 `queries.posting_skills(conn, job_id=None)`: marks plus the verified suggestions from the latest succeeded run on the latest snapshot, minus rejected keys. Marks win, and skills are identified by `name_key`. Verify with query tests matching "Marks and suggestions combined" and "Unverified suggestion left out", plus a run on an older snapshot being ignored.
- [x] 7.2 `skill_embeddings` storage in `derived.py` (float32 `LargeBinary`, one row per model and text key) and the shortlist: cosine similarity in pure Python, `SHORTLIST_K = 5`, `SHORTLIST_FLOOR = 0.45`, and the model's prefix where it has one. Verify with tests that a vector round-trips on SQLite and Postgres, that names are embedded only once per model, and that "Nothing similar" makes no chat request.
- [x] 7.3 The `link-judge@1` step (now `@2`, see 10.4) (top-level field `relations`), with judgments stored by `derived.py` in `link_judgments` and `link_relations`. Verify with `FakeLLM` tests matching "Specific form" and "Strongest relation wins", and "Re-judging keeps history".
- [x] 7.4 `queries.effective_link`, checking in order: override (ignored and flagged stale when its skill has left the profile), same key, latest judgment (relations to skills outside the profile ignored), no link. Overrides are written by `userdata.set_link_override` and cleared by `userdata.clear_link_override`. Verify with tests matching "Same identity", "Link used before review", "Overriding a model link" and "Stale override".
- [x] 7.5 `links.plan(conn)`: a key is judged when it has no override, no same-key profile skill, and either no judgment or a changed candidate set or embedding model. Add a "re-judge all" variant. Verify with planner tests matching "New closer profile skill" and "Nothing changed", and that a chat-model change alone plans nothing.

## 8. Queue (D10, D11)

- [x] 8.1 Make `jobs` dispatch by `kind`:
  - `posting`: unchanged
  - `document`: runs the document pipeline, saves the run, then calls `merge_run` and queues links in the same transaction
  - `links`: runs the plan, then judges key by key, checking for cancellation between keys and keeping finished judgments.
  
  Recovery and the `Unreachable` wait apply to every kind. Verify with jobs tests matching "Mixed kinds in order", "Cancelling link judging midway", and the existing queue tests passing unchanged.
- [x] 8.2 Automatic queuing:
  - `enqueue_document` runs after a `cv` upload with extracted text, and from the "Add to profile" action
  - `enqueue_links` does nothing while a links job is queued, and queues another if one is running.
  
  Call `enqueue_links` from: merge, rollback, adding, renaming or removing a profile skill, a successful posting run, adding or removing a mark, rejecting or undoing a rejection, and an embedding-model change. Verify with tests matching "Uploading a CV", "Adding another document", "Document without text" and "Changes coalesce", and one test per trigger that a links job gets queued.

## 9. Web (D12)

- [x] 9.1 The `/profile` page:
  - sections, entries and items with inline htmx edit, add, delete and up/down
  - model rows styled `.src-derived` with a "from model" badge
  - the skills panel grouped by level, with evidence links, a level control, and the posting skills linked to each skill
  - "Profile" in the navigation.
  
  GET handlers stay read-only. Verify with web tests (Flask test client) matching "Viewing the profile", one test per edit action, and the Origin check on every new POST route.
- [x] 9.2 The `/profile/history` page (merges with rollback and "merge again", deletions with "forget") and `/profile/links` (sorted by posting count, showing source, override controls, "re-judge all", and the "no embedding model" notice). Verify with web tests matching "Most-asked skills first" and the override and rollback actions.
- [x] 9.3 Existing pages:
  - the document page gets "Add to profile" (disabled while Ollama is down or the document has no text) and its list of merges
  - the skills page shows the five levels and profile membership
  - the settings page gets the embedding model
  - the queue shows each job's subject.
  
  Verify with web tests matching "Setting a level", "Skills page" and the queue subjects in "Mixed kinds in order".

## 10. Docs, full run and real-data check

- [x] 10.1 Update CLAUDE.md:
  - project status
  - architecture (the new modules)
  - "Four data kinds" (the new tables and their writers)
  - "Model enrichment" (the embedding setting, automatic queuing, linking)
  - the profile workflow
  - "Data and backups" (going below `0005_profile` drops the profile, merge history and link judgments).
  
  Verify with `grep -n "profile\|0005\|embed" CLAUDE.md`.
- [x] 10.2 Run `pytest`, the Postgres run if `JOBHUNT_TEST_PG_URL` is available, and `openspec validate add-cv-skill-profile --strict`. Verify that all pass.
- [x] 10.3 Check text extraction on real data, with no GPU: run `documents.extract_text` on `data/cv.odt` and the `caps@1` step on the result. Verify that five headings come out with the kinds `summary`, `claims`, `experience`, `education` and `publication`, that dated lines keep their tab, and that the contact block is a `contact` section. Report counts and kinds only, without personal details.
- [x] 10.4 Ask the user before any model runs on their GPU. With their approval, upload `data/cv.odt` through `jobhunt serve` on the real database (migrated, with the 0.2 backup in place), and let the CV extraction and the first link pass run. Verify with the user on `/profile` and `/profile/links` that the sections, entries, skills and top links look right. Record the number of link requests the first pass made.
  - First pass (2026-10-05, gemma4:12b, nomic-embed-text, floor 0.45, `link-judge@1`): 223 link requests, every posting skill shortlisted. Re-judge with floor 0.75 and `link-judge@2`: 150 requests in 4.5 min; model `same` links 36 → 20. The user reviewed `/profile` and `/profile/links` and accepted this state; directions for further improvement are in design.md, "Open Questions".
