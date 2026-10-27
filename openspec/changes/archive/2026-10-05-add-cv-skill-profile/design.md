## Context

See proposal.md for motivation. The current state this design builds on:

- **Documents.** `documents.py` stores uploads by content hash and extracts text from PDF, DOCX, TXT and MD. `documents.kind` is `cv`, `cover_letter` or `other`. Nothing reads `text_content` after upload.
- **Skills.** `skills` is `(id, name, key, level, updated_at)`, with `level` in `have / missing / learning` (all 224 rows NULL today). Marks point at `skills` rows. Suggestions live in `enrichment_skills` as name and key only, so a suggested skill that was never marked has no `skills` row. `userdata.name_key` gives a skill's identity.
- **Pipeline contracts.** A step sees text plus `LLM.chat_json(system, user, schema)` and never Ollama directly. `validate.locate(text, quote, within)` finds a quote by whole word, preferring a given span, and returns raw offsets. Every chat request uses temperature 0, seed 7, the context size and a JSON schema.
- **Queue.** `llm_jobs` requires `job_id` and `snapshot_id`, so it can only hold posting extraction. One `jobs.Worker` thread runs jobs in order. `Unreachable` leaves a job queued. Nothing is queued without a user request.
- **Ollama.** `OllamaClient.models()` reports each model's capabilities from `/api/show`. `"completion"` marks a text model. Embedding-only models (such as the installed `nomic-embed-text`) report `"embedding"`. There's no embedding call yet.
- **The user's CV** (seen during exploration, not committed) is one ODT file:
  - a contact block laid out as a table
  - headings that are short paragraphs in capitals, not heading elements
  - a "skills & experience" list of claim bullets ("N+ years experience with X (incl. A, B)")
  - one role with dated course lines, degrees, and publications
  - dates right-aligned after a tab stop on every dated line.

## Goals / Non-Goals

**Goals:**
- Model output feeds the profile and links without a review step, but nothing the user has authored is ever overwritten, and anything the model did can be undone.
- Links stay accurate as the profile and the postings change, and only what changed is re-judged.
- The structures the next change (`add-skill-match`) needs are in place: the posting skill set and the effective link per posting skill.

**Non-Goals:**
- Scores, credit values and gap displays (`add-skill-match`).
- Generating CVs, or storing formatting such as fonts, emphasis or page layout.
- Layout recovery for multi-column PDFs. The user's sources are ODT files or manual edits.
- Merging near-duplicate profile skills automatically.

## Decisions

### D1. Data kinds: the profile is user-authored, runs and judgments are derived

```
 [derived, enrich/derived.py]                 [user-authored, userdata.py]
  document_runs ------- merge ------------->  profile_sections / profile_entries / profile_items
   (never edited)    (copies verified,        skills.level (+ level_origin), skill_evidence
                      origin='model')         profile_deletions, profile_merges(+_changes)
  skill_embeddings                             skill_link_overrides
  link_judgments(+ link_relations) --------->  (read together: override, else latest judgment)
```

- **The profile is the user's, even where the model wrote it.** A merge works like `accept_suggestion` does today: `userdata` reads a verified derived result and copies it into user tables, marking each row `origin='model'`. The only differences from accepting are that it's automatic and logged.
- **Link judgments stay derived, and overrides are user-authored.** The effective link is computed when read, so an override takes effect at once, and a new judgment never touches an override.

*Alternative:* treat model-made profile rows as derived until edited. Not taken: a row would move between data kinds when edited, and both writers would need to touch the same tables.

### D2. Profile schema

```
 profile_sections   id, name, kind, position, origin, created_at, updated_at
                    kind: contact | summary | claims | experience | education | publication | project | other
 profile_entries    id, section_id, title, organisation, location, start_date, end_date, ongoing,
                    url, position, origin, created_at, updated_at
 profile_items      id, section_id, entry_id (NULL = directly under the section), label, text,
                    start_date, end_date, position, origin, created_at, updated_at
 skills             + level_origin ('model' | 'user'); level scale changes (D3)
 skill_evidence     id, skill_id, item_id | entry_id (exactly one), quote, claimed_years,
                    document_id, origin, created_at
```

- **One set of tables for every section kind.** The kind decides which fields the UI shows and how extraction treats the section. A publication uses `title` for the citation, `organisation` for the venue, and `end_date` for the year. Contact details are items with a `label` ("Email"). No type-specific tables and no JSON columns, so the schema stays portable.
- **Dates are partial ISO text** (`2022` or `2022-09`), with `ongoing` for "present". CVs rarely give days, and text compares correctly at both precisions.
- **`origin` starts as `model` or `user`.** Any user edit of a row's content sets it to `user`. Reordering doesn't change origin, because merges never move existing rows.
- **Profile membership:** a profile skill is a `skills` row with a level. Setting a level on any skill (including from the skills page) adds it to the profile. Clearing the level removes it, together with its evidence. Using the same rows means a posting mark and a profile skill with the same key are the same skill, and link trivially as `same` (D8).

### D3. Level scale

`SKILL_LEVELS = ("missing", "learning", "familiar", "proficient", "expert")`, an ordered scale. Migration `0005` maps existing `have` values to `proficient`. The user's database has none, but others might. `level_origin` is `model` when a merge set the level, and `user` after any user change.

*Alternative:* a separate strength column next to `have / learning / missing`. Not taken: it allows combinations that make no sense (`missing` + `expert`). One scale also gives the next change one credit value per level.

### D4. ODT text extraction

`documents.extract_text` handles `.odt` with `zipfile` and `xml.etree`, reading `content.xml`:
- **One line per paragraph, heading and list item, in document order.** Table cells are read row by row, one line per paragraph in a cell.
- **Tab stops become `\t`**, `text:s` becomes its count of spaces, and `text:line-break` becomes a newline.
- **Skipped:** images, frames without text boxes, tracked-change records (`text:tracked-changes`) and annotations. Text boxes inside frames are read in place.
- **Headers and footers** (in `styles.xml`) aren't read. CVs rarely put content there.

Tabs are kept because dates sit after them. The line labeller (D5) is told that a tab-separated tail is usually a date.

### D5. The document pipeline

The pipeline id has the same form as the posting one, so runs can be compared: `cvseg=caps@1 cvlines=llm@1 cvskills=cv-atomic@1 validate=v@3`. Steps keep the span contract (`Segment` offsets into `text_content`), so quotes stay checkable.

1. **`caps@1` sections (rules, no model).** A line is a heading when the text before its first tab has at least two letters, all of them capitals, and is at most 60 characters. That handles a heading with a tabbed note after it, as in the user's CV. Lines before the first heading form a `contact` section. The kind comes from keywords in the heading, checked in this order: summary, goals, objective, profile → `summary`; skills → `claims`; experience, employment, work, teaching → `experience`; education → `education`; publication → `publication`; project → `project`; otherwise `other`. "Skills & experience" therefore becomes `claims`. The user can change a section's kind afterwards.
2. **Contact fields (rules, no model).** Emails, URLs and phone numbers are recognised by pattern. The first line is the name, and other lines become unlabelled items. Contact content is never sent to the model.
3. **`llm@1` line labelling.** For each `claims`, `experience`, `education`, `publication`, `project` and `other` section, numbered lines go to the model, which labels each as `entry`, `bullet`, `detail` (continues the previous entry, like a thesis title or course lines) or `text` (prose). For an `entry` it also returns quotes for the title, organisation, location and dates. For a `bullet` or `detail` it returns date quotes if there are any. Text left over on an entry line becomes the entry's first bullet. `summary` sections become `text` items without a model call.
4. **`cv-atomic@1` skills.** One call per section that can hold skill evidence (`claims`, `experience`, `education`, `publication`, `project`), with numbered lines. Each item returns `line`, `name`, `kind` (`technical | soft | qualification`; certifications count as qualifications), `quote`, `years` (an integer or null) and `level` (`familiar | proficient | expert`). The prompt asks what each line *shows the person has*. Unlike the posting prompt, it includes research methods and subject expertise ("evolutionary computation", "constrained optimisation"), since on a CV those are skills. It suggests a level from the wording and stated years: "familiar with" → familiar, "proficient with" → proficient, long stated experience → expert. The retry-once-on-empty pattern is reused per section.
5. **Validation (`v@3`, reused).** Every quote (field, date and skill) is located in its source line, then in the whole text. Dates must parse to a partial date. `years` counts only when that number appears in the source line. Unverified items stay in the run's trace and are never merged.

The result is stored as one `document_runs` row: `(id, document_id, text_sha256, model, pipeline, status, error, started_at, finished_at, output_json)`. `output_json` holds the verified structure (sections, then entries and items, then skills with offsets) plus the step trace. No item tables are needed, because only the merge reads a run.

*Alternative:* reuse the posting segmenter and `atomic@2` unchanged, as `add-ollama-enrichment` planned. Not taken: a CV needs entries and dates, not required/preferred labels. And the posting prompt's exclusions (subject domains) are wrong for a CV.

### D6. Automatic merge

When a document run succeeds, the worker calls `userdata.merge_run(conn, run_id)` in the same transaction that finishes the job. Matching is conservative and exact, so a wrong merge is unlikely, and when one happens it's easy to see and undo:

| Run item | Matches an existing row when | On a match | No match |
|---|---|---|---|
| section | same kind and same `name_key(name)` | nothing | append |
| entry | same section, and the same `name_key` of title and organisation | fill fields that are empty on a model-origin row | append |
| item | same parent and the same normalised text | nothing | append |
| skill | same key | add evidence. If `level_origin` is model, raise the level to the higher of the two | set level, `level_origin='model'` |
| evidence | same skill and the same target row | nothing | add |

- User-origin rows are never changed by a merge.
- Rows are never moved, and new ones are appended at the end of their parent.
- Before inserting anything, the merge checks `profile_deletions` (D7) and skips content the user deleted.

**Merge log.** `profile_merges` is `(id, run_id, document_id, created_at, rolled_back_at)`. `profile_merge_changes` is `(merge_id, seq, table_name, row_id, action, before_json)`, where `action` is `insert` or `update`. `before_json` holds the previous values of the columns an update filled in.

**Rollback** (`userdata.rollback_merge`) walks the changes in reverse order:
- An inserted row is deleted (with its evidence) if it's still `origin='model'` and hasn't been updated since the merge.
- An updated row gets its previous values back under the same condition.
- Rows the user has since edited are kept, and listed in the rollback's result.

A rolled-back merge stays in the log, marked rolled back, and offers "merge again".

*Alternative:* fuzzy matching (embedding similarity of entries). Not taken: an automatic merge that's wrong in a subtle way is worse than a duplicate the user deletes. It could be added later as a suggestion.

### D7. Editing and remembered deletions

`userdata` provides add, edit, delete and move up/down for sections, entries and items; set level, add and remove skills; and add and remove evidence. Editing sets `origin='user'` and `updated_at`.

Deleting writes a `profile_deletions` row `(id, kind, fingerprint, label, deleted_at)`. The fingerprint is built from the same keys the merge matches on (D6), with the parent's fingerprint as a prefix. Deleting an entry or section also deletes its children, and the parent's fingerprint covers them. The merge skips any run item whose fingerprint, or whose parent's fingerprint, has been deleted. The merge history page lists deletions with a "forget" action, which removes the record. The content itself isn't recreated. Merging the document again brings it back.

Every deletion is recorded, whether the row came from the model or the user. That's simpler, and harmless: a user-added row would only come back if a document contained exactly the same content.

### D8. Posting skills and the effective link

`queries.posting_skills(conn, job_id=None)` is shared with the next change. For each posting:
- every mark, with its skill, importance and quote
- plus the verified suggestions from the latest succeeded run on the posting's latest snapshot, whose key isn't rejected for that posting and isn't already marked.

When a mark and a suggestion share a key, the mark wins. A posting skill is identified by its key.

`queries.effective_link(posting_key)` checks, in order:
1. **Override** (`skill_link_overrides`: `posting_key` PK, `skill_id` NULL meaning "no link", `relation`, `created_at`). It applies if its skill is still in the profile. Otherwise it's shown as stale and ignored.
2. **Same key.** If a profile skill has the same key, the relation is `same`, with no model call and nothing stored.
3. **Latest succeeded judgment** for the key, keeping only relations whose skill is still in the profile. The best relation wins in the order `same > specific > general > related`, with ties going to the higher similarity.
4. Otherwise, **no link**.

**Relations,** from the profile skill's point of view:

| Relation | Meaning | Example (posting, then profile) |
|---|---|---|
| `same` | the same skill | `LLMs`, then "Large language models" |
| `specific` | the profile skill is a specific form of the posting skill | `CI/CD`, then "GitHub Actions" |
| `general` | the profile skill is a more general form | `LoRA`, then "LLM fine-tuning" |
| `related` | they overlap, but neither is a form of the other | `MLOps`, then "Docker" |

Credit per relation belongs to `add-skill-match`.

### D9. Embeddings and the shortlist

- **Client.** `OllamaClient.embed(model, texts)` calls `/api/embed` in batches. Embedding requests have no sampling options, so the request-options requirement exempts them.
- **Storage.** Vectors go in `skill_embeddings` `(model, text_key, vector)`: a derived table with `vector` as `LargeBinary` (little-endian float32, which is portable). Rows are computed once per model and text.
- **What gets embedded.** The skill's display name. Where the model recommends a prefix for symmetric similarity, it's added (`nomic-embed-text`: `clustering: `).
- **Similarity.** Cosine similarity in pure Python. About 250 posting keys × 60 profile skills is far too small to need numpy.
- **Shortlist.** For each posting key with no override and no same-key profile skill: the top `SHORTLIST_K = 5` profile skills with similarity of at least `SHORTLIST_FLOOR = 0.45`. If none qualifies, the key has no link and no model call is made. Both are module constants, since their values are an implementation detail to tune on real data.
  *Tuned on real data:* nomic-embed-text scores any two skill names 0.65 or more, so 0.45 shortlisted everything (223 of 223 posting skills judged, many weak links). The floor is now 0.75 (150 judged).

The embedding model setting (`llm.embed_model`) defaults to `nomic-embed-text` when it's installed, and lists only models whose capabilities include `embedding`.

### D10. Judging, and deciding what to re-judge

- **Requests.** `link-judge@2` makes one chat request per posting key. It sends the posting skill's name and one quote for context, plus the shortlisted profile skills (name, kind, and one evidence quote each). The model returns a relation for each candidate (`same | specific | general | related | none`).
  *`@2` after the first real pass:* `@1` judged 36 links `same` that were related at best ("agent frameworks" = "agentic AI workflows", "LLM evaluation" = "assessment design"). `@2` defines `same` as a name a recruiter would count as the skill itself, gives examples of `none`, and asks for the weaker relation when in doubt (20 `same` links remained).
- **Storage.** Results go in `link_judgments` `(id, posting_key, posting_name, model, embed_model, pipeline, candidates_json, status, error, created_at, output_json)` and `link_relations` `(judgment_id, skill_id, relation, similarity)`.

**Re-judging by comparing shortlists.** The `links` job runs `links.plan(conn)`. For each posting key with no override and no same-key profile skill, it computes the current shortlist (D9) and compares it with the `candidates_json` of the key's latest judgment. A key is judged when it has no judgment, or when the set of candidate skill ids or the embedding model differs. This covers every trigger with one rule:
- A new posting skill has no judgment.
- A new or renamed profile skill enters some shortlists.
- A profile skill leaves the profile and drops out of shortlists.

Changing the chat model doesn't trigger re-judging by itself. The links page has a "re-judge all" action for that.

**When the job is queued.** It's queued automatically after:
- a merge, or a profile skill being added, renamed or removed
- a posting run that succeeds
- a mark being added or removed, or a rejection being added or undone
- a change of embedding model.

`jobs.enqueue_links` does nothing when a `links` job is already *queued*. If one is *running*, another is queued, because the running job may have planned before the change. The job is cancellable between keys. Judgments already stored stay.

*Alternative:* judge every pair of posting skill and profile skill. Not taken: about 15,000 pairs instead of about 250 keys, and most pairs are obviously unrelated.

### D11. Generalised queue

Migration `0005` changes `llm_jobs`:
- adds `kind` (`posting` (default for existing rows), `document`, `links`)
- makes `job_id` and `snapshot_id` nullable
- adds `document_id` and `document_run_id`.

The rest stays as it is:
- Jobs run oldest first across all kinds, `Unreachable` leaves any kind queued, and recovery, cancelling and the queue page apply to every kind.
- The model is fixed when the job is queued, so a settings change leaves queued work alone.

The queue page shows each job's subject: a posting link, a document label, or "skill links".

**Document jobs are queued automatically** when a document of kind `cv` is uploaded and its text was extracted, and by the "Add to profile" action on any document with text. Re-extracting adds a run, and merging it again adds only what's new.

### D12. Web interface

- **`/profile`**:
  - sections in order, each with its entries and items
  - inline edit forms (htmx), add, delete, and up/down buttons
  - rows with `origin='model'` styled `.src-derived` with a "from model" badge, until edited
  - a skills panel grouped by level, with each skill's evidence linking to its rows and a level control.
- **`/profile/history`**: merges (document, time, counts) with rollback and "merge again", plus deletions with "forget".
- **`/profile/links`**:
  - every posting skill: name, number of postings, effective link (profile skill and relation), and source (same key, model or yours)
  - override controls: choose a profile skill and a relation, or "no link"; clear the override
  - sorted by number of postings, so links that matter most come first
  - the "re-judge all" action.
- **Navigation** gains "Profile". Document pages gain "Add to profile" and list their merges.

Route modules stay thin. Logic lives in `userdata.py`, `queries.py` and the `enrich/` modules, all tested without Flask.

### D13. Tests

- **Fakes.** `FakeLLM` scripts answers by the schema's top-level field, so the new schemas use distinct top-level fields: `lines`, `cv_skills`, `relations`. `FakeOllama` gains a deterministic `embed` based on character trigram counts, so that similar names really are similar in tests.
- **Fixtures.** ODT fixtures are built in the tests (a zip written in code), including tabs, a table, a list and a tracked change. The user's CV is never committed. A golden test against `tests/fixtures/private/` runs only when present, like the posting goldens.
- **Merge.** Merge, rollback and deletion tests cover:
  - user edits surviving a merge and a rollback
  - deleted content not coming back
  - level raising for model levels only
  - "merge again".
- **Links.** Planner tests cover each re-judging trigger, and that overrides are never judged.
- **Migration.** `tests/test_migrate.py` covers `0005`, on Postgres too.

## Risks / Trade-offs

- **[A wrong link counts until noticed (D3)]** → The links page shows each link's source and sorts by posting count, so the highest-impact links get looked at first. Overrides take effect at once and are never re-judged.
- **[Automatic GPU work the user didn't start]** → Jobs are visible and cancellable on the queue page. Link jobs coalesce and judge only changed shortlists. The first full pass (about 250 short calls) happens after the first CV merge, and later passes are small.
- **[Conservative merge creates duplicates]** (an entry retitled between CV versions) → The duplicate is visible and the user deletes it. That deletion is remembered, so the old version doesn't come back.
- **[Line labelling mistakes]** (a course line taken as an entry) → The rows are marked "from model" and are easy to edit. Rollback and "merge again" let the user retry after re-extracting with another model.
- **[The shortlist floor hides a real link]** → The posting skill appears with no link on the links page, and the user can link it by hand. The floor is a constant, easy to retune.
- **[Shared `skills` rows]**: setting a level from the skills page now adds the skill to the profile → That's intended (a level only means something about the user). The skills page shows profile membership.
- **[A profile skill renamed to a posting skill's key]** turns a model link into `same` silently → That's correct, and the change is visible on the links page.

## Migration Plan

One Alembic revision, `0005_profile`:
- Creates the profile, evidence, deletion, merge-log and override tables, and the derived `document_runs`, `skill_embeddings`, `link_judgments` and `link_relations`.
- Adds `skills.level_origin` and maps `have` to `proficient`.
- Changes `llm_jobs` with `render_as_batch` (D11).

`downgrade()` drops the new tables, deletes non-posting jobs before restoring the `NOT NULL` columns, and maps `familiar`, `proficient` and `expert` back to `have`. CLAUDE.md's backup note gains: going below `0005_profile` drops the profile, its merge history and the link judgments.

## Open Questions

- The shortlist constants (`SHORTLIST_K`, `SHORTLIST_FLOOR`) may need retuning once the user's real profile and posting skills exist. That's a constant change, with no effect on specs.
- **Link quality after the first real pass** (`link-judge@2`, floor 0.75), directions to try, each re-judged with "Re-judge all" (about 150 requests):
  - Forbid `same` when one skill is evaluating, building or using the other ("Evaluating LLM agentic solutions" and "agentic loops" are still judged the same as "agentic AI workflows").
  - Add a "broader skill → general" example ("Communication" for "Technical communication" was judged `related`).
  - Retune `SHORTLIST_FLOOR` (0.8 would judge 77 posting skills instead of 150) or make it relative to each key's best match.
  - Measure judging against a few hand-linked posting skills before changing the prompt again, instead of reading the links page.
- **CV skill quality:** `cv-atomic@1` produced fragments ("Chain" for LangChain, "Constrained Problem" from a publication title) and over-specific names ("serverless CI/CD"). Bad profile skills cause bad or missing links (152 of 232 posting skills have none). Options: ask for a skill's usual name, not a fragment of a title; skip skills quoted only from publication titles; or flag single-word skills that aren't known tools.
- **Structure:** the teaching entry got no dates, and each publication keeps the whole citation as its title with no venue.
- Whether contact details need structured fields (separate city and country, several URLs by type) depends on what CV generation needs. Labelled items cover today's content.
