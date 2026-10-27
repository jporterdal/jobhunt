## Context

See proposal.md for motivation, and `specs/tailored-cv/spec.md` for the behaviour. The current state that shapes the approach:

- **The knowledge base** (`restructure-profile-knowledge-base`, implemented, not yet archived): `records` with lines, sources, disclosure and `part_of_id`; `claims` (one per skill, with the level); grounds (`claim_records`); `highlights` covering claims (`highlight_claims`); `profile_details`. `queries.profile(conn)` already returns records grouped by kind and sorted by `record_sort_key`, each with lines, sources, `effective_disclosure`, its context and dependents and the claims it grounds, plus claims and highlights with their coverage.
- **Matching** is already computed per posting by `recommend.posting_summary`: `queries.posting_skills` (key, name, importance), `queries.effective_links` (each key's `options`: profile `skill_id` and relation, aliases resolved), levels from `queries.profile_skills`, and the weights `RELATION_WEIGHT`, `LEVEL_WEIGHT` and `IMPORTANCE_WEIGHT` at the top of `recommend.py`.
- **The user's data** (read-only check, 2026-10-16): 31 records of five kinds, most of them courses, publications and projects (none private, none with `part_of` yet), 16 highlights (the 9 "Skills & Experience" lines, 4 keyword-list lines covering 6–9 claims each, 3 portfolio section intros), 82 claims, 12 details, no applications. The role's lines repeat the course list, three publications appear twice (a citation and a title-with-venue record each), and two upgrade leftovers remain among the details (a headline and a date stored as contact details).
- **The reference CV** (`cv.odt`, document 1) runs: name, headline, date and contacts; a goals statement; a skills list (9 bullets); work experience (the role, with courses by year); education (degrees, a thesis under its degree); selected publications. No projects.
- **Documents** are read by `documents.odt_text` (stdlib `zipfile` + `ElementTree`), so an exported ODT can be read back in tests with no new dependency.

## Goals / Non-Goals

**Goals:**
- A proposal that needs no model and no writes, so it is cheap to open for every posting and safe to re-open.
- Presentation that can be changed in one place: the look in `cvdoc/styles.py`, the wording and order in `cvdoc/layout.py`, never in selection or storage code.
- A saved CV that is a faithful record of what the app produced, independent of later profile edits.
- Portable SQL only (SQLite and Postgres), and one writer per data kind as today.

**Non-Goals:**
- Everything listed under "Deferred" in proposal.md.
- Editing text inside the app. Wording changes go to the library on the profile page (for every later CV) or into the exported ODT (for this one).
- Merging duplicate records, or warning about them. The user cleans up the knowledge base.
- Tuning the weights against outcomes. Like `recommend.py`'s, they are guesses until there is data.

## Decisions

### D1. Modules and data flow

```
 queries (profile, posting_skills, effective_links, profile_skills)
        |
        v
 tailor.py  -- propose(conn, job_id, choice) -> Proposal   (read-only; cv-rank@1)
        |                                   \
        | (web: GET proposal, preview)       \ userdata.save_tailored_cv(conn, job_id, proposal, now)
        v                                     v
 cvdoc/layout.py  build(content) -> Cv    tailored_cvs + tailored_cv_items (frozen content, JSON)
        |                                     |
        +-------------<-----------------------+  (a saved CV's content goes through the same build)
        v
 Cv (cvdoc/model.py: header, sections, entries, lines)
        |------------------------------|
        v                              v
 templates/cvs/_preview.html      cvdoc/odt.py write(cv) -> bytes, using cvdoc/styles.py
```

- `tailor.py` sits beside `recommend.py`: no Flask, no writes, no model. It imports the weights from `recommend.py` instead of copying them, so a posting skill's value in a CV matches its credit on Insights.
- The **content** (what to print: frozen field values) is kept apart from the **layout** (how to word and order it) and the **styles** (how it looks). A proposal and a saved CV both produce the same content structure, and `layout.build` turns either into a `Cv`. That is why the preview and the export cannot drift apart, and why a later change can restyle saved CVs without touching their content.
- New package `src/jobhunt/cvdoc/` (not `cv`, which would be confused with `enrich/cv.py`, the document pipeline):
  - `model.py`: frozen dataclasses `Cv(header, sections)`, `Header(name, headline, produced, contacts)`, `Section(key, heading, blocks)`, and block types `Paragraph(text)`, `Bullet(text)` and `Entry(title, subtitle, dates, lines, sources, context_note, children)`. Plus `content_to_json` / `content_from_json` for the stored content.
  - `layout.py`: `SECTION_ORDER`, `HEADINGS`, date and term wording, course condensing, nesting by `part_of`, and `build(content) -> Cv`.
  - `styles.py`: the ODF `styles.xml` (fonts, sizes, margins, a right tab stop for dates, the bullet list style) and the style names that `odt.py` uses.
  - `odt.py`: `write(cv) -> bytes`.

### D2. Ranking: `cv-rank@1`

`tailor.METHOD = "cv-rank@1"` is stored on each saved CV. Bump the version whenever selection output changes for the same data, following the project's `name@version` convention, so CVs from different rankings aren't taken for the same.

Constants at the top of `tailor.py`:

| Name | Value | Meaning |
|---|---|---|
| `HIGHLIGHT_BUDGET` | 9 | the user's CV has 9 |
| `IRRELEVANT_COST` | 0.1 | per covered claim no posting skill has an option to |
| `KIND_RULES` | `role`, `course`, `degree`, `award`: `"all"`; `publication`: 3; `project`, `event`, `task`, `other`: 0 | counts are defaults the user can change per proposal |
| `DEFAULT_DETAILS` | `name`, `headline`, `contact`, `goal` | `summary` off by default |

**Values.** For posting skill `s` with weight `w(s) = IMPORTANCE_WEIGHT[importance]` and link options `O(s)` (from `effective_links`, already alias-resolved to profile skill ids), `value(s, k) = w(s) × RELATION_WEIGHT[rel] × LEVEL_WEIGHT[level(k)]` for each profile skill `k` in `O(s)`. A claim is identified by its skill id, as `effective_links` returns it.

**Highlights (greedy weighted cover).** Let `shown[s]` start at 0. Repeat until the budget is reached:
- `gain(h) = Σ_s max(0, max_{k ∈ claims(h)} value(s, k) − shown[s]) − IRRELEVANT_COST × |{k ∈ claims(h) : no s has k in O(s)}|`
- Take the highlight with the highest gain, if that gain is above 0. Ties go to fewer covered claims, then the lower id.
- Update `shown[s]` to the best value the chosen highlight gives.

This is the standard greedy for weighted maximum coverage. Because `shown` only rises, a skill already shown adds nothing, which is the "don't cover a claim twice" rule from the handoff. The cost term stops the four keyword-list highlights (6–9 claims each) from winning on breadth alone, while still letting one win when most of what it lists is asked for. Highlights the user ticks by hand go after the chosen ones, in id order. Highlights the user unticks are skipped by the greedy, so the budget goes to the next best.

- *Alternative:* rank highlights by their own total value, with no "already shown" term. Not taken: two Python highlights would both make the top 9.
- *Alternative:* a length budget in characters. Not taken for now: the user's CV is counted in bullets, and the count is easy to change per proposal.

**Records.** `relevance(r) = Σ_s max_{k ∈ grounds(r) ∩ O(s)} value(s, k)` (0 when there's none). The best value counts per posting skill, so a record grounding Python, Django and PostgreSQL scores all three. That is the "co-grounding" idea from the handoff, without any extra structure. For a ranked kind with count `n`, sort by `(-relevance, record_sort_key)` and take `n`, then print in `record_sort_key` order. A record ticked by hand is added even past the count. One unticked is never taken.

**Gaps.** For each posting skill with `recommend.credit > 0`: if no chosen highlight's claims and no chosen record's grounds meet `O(s)` at a level above `missing`, it is a gap. It shows the best option's profile skill, and whether any highlight in the library covers that skill.

**Private records** are removed from the candidate records before any of this (D6), so they cannot raise a relevance, fill a count or close a gap.

### D3. Proposal state lives in the URL

`GET /postings/<job_id>/cv` is read-only, so the proposal's choices are query parameters:
- `budget`, `count_<kind>`;
- `h`, `r`, `d`: the ticked highlight, record and detail ids;
- `x_h`, `x_r`, `x_d`: the unticked ones;
- `tuned=1` once the user has submitted the form.

Without `tuned`, the defaults apply. With it, the explicit ticks and unticks override the ranking, and everything else is ranked. The form is a plain GET, with htmx swapping the preview, gaps and choice lists. `tailor.Choice.from_args(args)` is the only parser, following `recommend.workplace_choice`.

Saving is `POST /postings/<job_id>/cvs` with the same fields. The server parses the choice, calls `tailor.propose` again inside the write transaction, and saves that result. It never stores text sent by the browser, only ids, so a saved CV always matches the profile at the moment of saving. A private record id in the choice is ignored, because it isn't a candidate.

- *As built:* a checkbox the user unchecks isn't sent at all, so the form also sends `a_h`, `a_r`, `a_d`: the ids the ranking chose by itself. `from_args` takes ticks as the checked ids minus those, and unticks as those (and earlier `x_*`) left unchecked; a checked `a_*` id stays with the ranking. The canonical URL (`Choice.to_args`) has only the fields above.
- *Alternative:* a mutable draft row that the proposal page edits. Not taken: it needs writes on every tick, and a cleanup of abandoned drafts. The read-only GET follows the "keep GET handlers read-only" rule in `web/guard.py`.

### D4. Tables (revision `0009_tailored_cv`)

Both tables are user-authored, written only by `userdata.py`, and listed in `db.USER_TABLES`.

| Table | Columns | Notes |
|---|---|---|
| `tailored_cvs` | id, job_id (FK postings, not null, index), method (`cv-rank@1`), content_version (int, 1), match_score (float, nullable), choice_json (the budgets, counts and ticks used), created_at, updated_at | `created_at` is the produced month. |
| `tailored_cv_items` | id, cv_id (FK tailored_cvs, not null, index), section (`header`, `goal`, `summary`, `highlights`, or a record kind), position, source_kind (`detail`, `highlight`, `record`, `course_group`), source_id (int, nullable, **no FK**), payload_json (Text), created_at | One row per top-level item in print order. |

- **Payloads** hold field values, not formatted text:
  - a detail: `{kind, label, text}`;
  - a highlight: `{text}`;
  - a record: `{kind, title, organisation, location, start_date, end_date, ongoing, lines: [...], sources: [url, ...], context: {title, organisation} | null, children: [<record payload>, ...]}`;
  - a course group: `{title, organisation, location, terms: [{start_date, end_date}], record_ids: [...]}`.

  The layout (dates, terms, headings) is applied when the CV is rendered, so presentation can change later. The content can't.
- *As built:* a record payload also holds its `id`, and a course group also holds the union of its records' `lines`, `sources`, `context` and `children`, so the saved CV's page can mark deleted or now-private records nested under another, and nothing a course record holds is lost. `choice_json` is `{"choice": ..., "left_out": [kind, ...]}`: the kinds with public records not printed, which picks "Selected Publications"; removing a record item from a saved CV adds its kinds.
- **No foreign keys to profile rows.** A saved CV must outlive the records and highlights it copied. `source_id` only lets the saved CV's page say "this record has since been deleted", and nothing reads it otherwise.
- **JSON as `Text`**, as in `profile_suggestions.payload_json`, so it is portable with no JSON operators.
- **`content_version`** marks the payload shape. `layout.build` reads version 1. A later change to the shape bumps it and keeps reading 1.
- `match_score` is `recommend.posting_summary(...)["score"]["score"]` at saving, `None` when the posting has no skills.
- **Writers** in `userdata.py`: `save_tailored_cv(conn, job_id, proposal, now) -> id`, `move_cv_item(conn, cv_id, item_id, direction, now)` (swaps positions with the neighbour in the same section; a no-op at either end), `remove_cv_item(conn, cv_id, item_id, now)` and `delete_tailored_cv(conn, cv_id)`. Children travel inside their parent's payload, so moving or removing the parent carries them.
- **Readers** in `queries.py`: `tailored_cvs_for_posting(conn, job_id)` (newest first) and `tailored_cv(conn, cv_id)` (the CV, its items, the posting's title, company and URL, and which `source_id`s no longer exist).

### D5. Layout rules (`cvdoc/layout.py`)

- **Header:** name, headline, the produced month ("October 2026"), then contact details in their stored order. A label is printed before its text when it has one ("Email: …").
- **Headings** (`HEADINGS`, one dict):
  - `goal` "Statement of Goals", `summary` "Summary", `highlights` "Skills & Experience";
  - `role` "Work Experience", `course` "Courses Taught", `degree` "Education";
  - `publication` "Selected Publications" when public publications were left out, else "Publications";
  - `project` "Projects", `award` "Awards", `event` "Events", `task` "Tasks", `other` "Other".
- **Dates:**
  - `2022` → "2022"; `2022-09` → "Sep 2022";
  - a range → "start – end"; ongoing → "start – present"; only one of the two → that one.
- **Courses** are grouped by `(name_key(title), name_key(organisation))` in `tailor`, which keeps one group per course when saving. The layout prints:
  - the group's title and organisation;
  - dates from the first term's start year to the last term's end year;
  - one line of terms, oldest first ("Winter 2024, Winter 2025, Winter 2026, Fall 2026").

  A term is named only when start and end fall in one term window of one year (the `enrich/terms.py` months). Otherwise it prints as dates.
- **Nesting** (`part_of`):
  - A chosen record whose context is also chosen becomes a child entry, printed under its parent after the parent's lines, and is removed from its own section.
  - Otherwise, a record with a context gets `context_note` "Part of: <context title>".

  Chains are followed only one level, since the effective context of a dependent's dependent is printed through its parent anyway.
- **Sources:** `repo`, `site` and `doi` addresses print as one line after the lines. `document` sources never print.

`SECTION_ORDER`, `HEADINGS` and the date wording are the only places to change for a different CV style.

### D6. Non-disclosure

- `tailor` drops every record whose `effective_disclosure` (from `queries.profile`) is `private` before ranking, ticking or saving.
- **Highlight flag:** casefolded substring match of the highlight's text against each private record's title, organisation (when 4 characters or more) and each source address with its scheme and `www.` removed. A flagged highlight is unticked by default and shows "mentions <record label> (private)". The user may tick it: the wording is theirs, and a match can be a false positive (a private record's organisation could be a common word).
- A saved CV keeps the content it copied. If a record is made private after a CV was saved, that CV still contains it. The saved CV's page marks items whose `source_id` record is now private, so the user can remove them.

### D7. ODT writer (`cvdoc/odt.py`, `cvdoc/styles.py`)

- **The package:**
  - a `mimetype` entry first, stored uncompressed, containing `application/vnd.oasis.opendocument.text`;
  - `META-INF/manifest.xml`;
  - `styles.xml` (from `styles.py`);
  - `content.xml`;
  - a minimal `meta.xml`.

  Every zip entry gets a fixed timestamp, so the bytes are deterministic and tests can compare them.
- `content.xml` is built with `xml.etree.ElementTree`, with ODF namespaces registered, so all text is escaped by the library, never by string concatenation. It uses only named styles from `styles.py`:
  - `CvName`, `CvHeadline`, `CvContact`, `CvHeading`;
  - `CvEntry`: title and subtitle, then a tab and the dates, with a right tab stop at the text width;
  - `CvLine`, `CvNote`, `CvSource`;
  - the list style `CvBullets` for highlights (a real `text:list`, so LibreOffice treats it as a list).

  Paragraph properties (fonts, sizes, spacing, margins) live only in `styles.py`.
- **Download:** `GET /cvs/<id>.odt` returns `write(build(content))` with `Content-Disposition: attachment; filename="CV - <company> - <title>.odt"`. The name keeps letters, digits, spaces, `-`, `_` and `.`, and is cut to 120 characters.
- **Tests:**
  - read the export back with `documents.odt_text` and compare it with the `Cv`'s text in order;
  - check the zip's first entry, and that it is stored uncompressed;
  - check that every style name used in `content.xml` is defined in `styles.xml`.

  Opening the file in LibreOffice is checked by hand, with the user (tasks).
- *Alternative:* `odfpy`. Not taken: a new dependency that doesn't help with styling. *Alternative:* python-docx (DOCX). Not taken: the user chose ODT, whose source format their CV already uses.
- **Later restyling** (the user's request): copying another CV's look means replacing what `styles.py` returns and keeping its style names. Nothing else changes.

### D8. Web interface

New blueprint `web/cvs.py`, thin, as the other route modules are:

| Route | Does |
|---|---|
| `GET /postings/<job_id>/cv` | proposal page: score, budgets and counts, the choice lists (highlights with gain and covered claims, records by kind with relevance, details), gaps, preview |
| `POST /postings/<job_id>/cvs` | saves (D3), 303 to the CV |
| `GET /cvs/<id>` | saved CV: preview from content, per-item move up/down and remove, "deleted since" and "private since" marks, download, delete |
| `POST /cvs/<id>/items/<item_id>/move` (`direction=up|down`), `POST /cvs/<id>/items/<item_id>/remove`, `POST /cvs/<id>/delete` | 303 back (delete goes to the posting) |
| `GET /cvs/<id>.odt` | the export |

- Templates: `cvs/proposal.html`, `cvs/cv.html`, `cvs/_preview.html` (a macro walking a `Cv`) and `cvs/_list.html` (the panel on `postings/detail.html` and `applications/application.html`).
- The panels are marked `.src-user`. The proposal's computed values (gains, relevance, gaps) are marked `.src-derived`.

### D9. What happened to HANDOFF.md §6

Every note deferred to this change, and what this design does with it:

| Handoff note | Here |
|---|---|
| Ranking by importance × relation × strength; grounding records by co-grounding | D2 (the level is the strength; co-grounding is relevance summed per posting skill) |
| Highlights: greedy weighted set cover within a length budget; don't cover twice; account for irrelevant claims | D2 (a count budget instead of length; `IRRELEVANT_COST`) |
| Drafting highlights with the model | Deferred (proposal); the gaps list says what to write |
| Checks: naming a skill none of its claims is about; overstating a level; flag on claim change | Deferred; only the private-record mention check is in (D6) |
| Rendering: private never shown; dependents with context; headings by kind; output format | D5, D6, D7 (ODT) |
| Keyword list from claims by `category` (on the claim) | Deferred; the existing keyword-list highlights can be chosen like any other |
| Skill kind weighting | Deferred |
| Description lines always printed or selectable | Always printed (D5); per-line selection deferred |
| Storing what was sent with each application | D4 (per posting, listed on its application) |

Notes in the knowledge-base change's proposal that this design also covers: condensing repeated course records (D5), and printing the month the CV was produced (D5). "N+ years" from grounding dates remains deferred.

## Risks / Trade-offs

- [The knowledge base's duplicates print twice: the role's course-list lines beside the course entries, and three papers recorded twice] → The generator stays literal. Tasks include cleaning these up with the user before the first real CV, and the preview makes them obvious.
- [The weights and `IRRELEVANT_COST` are guesses] → They sit in one table at the top of `tailor.py`. The proposal shows each highlight's gain and covered claims, so a bad pick is visible and can be unticked. A ranking change bumps `cv-rank@n`.
- [Word renders ODT a little differently from LibreOffice] → The user exports PDF from LibreOffice when sending. All styling sits in `styles.py`, so a fix is local.
- [Uploading the finished, hand-edited ODT as a `cv` document queues a profile extraction (GPU) and offers its lines back as suggestions] → Suggestions already in the profile match by identity and aren't offered. The CV's page notes that attaching the sent file with kind `other` avoids extraction.
- [A saved CV keeps content from a record later made private] → D6 marks such items on the saved CV's page. The export is the user's action.
- [Payload shape changes later] → `content_version`, with `layout.build` reading every version it has written.
- [The proposal URL grows with many ticks] → At most a few dozen ids. Well within URL limits.

## Migration Plan

1. Back up `data/` (database and documents), as for every revision.
2. `init_db` applies `0009_tailored_cv` on the next `serve` or `import`. It only adds two empty tables.
3. Rollback: `alembic downgrade 0008_knowledge_base` drops both tables and every saved CV. CLAUDE.md's downgrade note says so.

## Open Questions

- Heading wording and whether "Courses Taught" should print under "Work Experience" as the user's CV does. This is presentation only (`HEADINGS`, `SECTION_ORDER`), and easy to change after the user sees the first export.
- Whether `IRRELEVANT_COST` = 0.1 picks well on the user's data. Checked with the user on a real posting (tasks), and changed as a `cv-rank@2` if needed.
