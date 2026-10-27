## 1. Before starting

- [x] 1.1 Check that `restructure-profile-knowledge-base` is archived (its tasks 10.4 and 11.4 done, and `HANDOFF.md` deleted once design D9 here is confirmed to cover its §6); if not, ask the user whether to archive it first; verify with `openspec list` that only this change is in progress

## 2. Schema

- [x] 2.1 Add `tailored_cvs` and `tailored_cv_items` to `db.py` (design D4: no FK from items to profile rows, `payload_json` and `choice_json` as Text) and list both in `USER_TABLES`; verify `tests/test_migrate.py`'s table-kind checks pass
- [x] 2.2 Generate revision `0009_tailored_cv` against a scratch database at head (CLAUDE.md "Schema migrations"), review it for portability, and write `downgrade()` dropping both tables; verify `pytest tests/test_migrate.py` passes (the migrated schema equals `db.metadata`) and that upgrade, downgrade and upgrade again succeed on a copy of a 0008 database

## 3. Content model and layout (`cvdoc/`)

- [x] 3.1 Create `src/jobhunt/cvdoc/model.py`: the frozen dataclasses `Cv`, `Header`, `Section`, `Paragraph`, `Bullet` and `Entry`, and `content_to_json` / `content_from_json` for payloads at `content_version` 1; verify in `tests/test_cvdoc.py` that every payload kind (detail, highlight, record with children, course group) round-trips unchanged
- [x] 3.2 Create `cvdoc/layout.py` with `SECTION_ORDER`, `HEADINGS`, date wording (year, month and year, ranges, "present") and term naming (the `enrich/terms.py` windows); verify tests for `2022`, `2022-09`, an ongoing record, a range with only an end, and a term that doesn't fit a window
- [x] 3.3 Add `layout.build(content) -> Cv`: the header with the produced month and labelled contacts, sections in order with empty ones left out, records with lines and printable sources (not `document` sources), condensed course groups, children under their parent, "Part of: …" notes, and "Selected Publications" when public publications were left out; verify tests for the spec's "Condensed course", "Produced month", "Empty section", "Thesis under its degree" and "Context not chosen" scenarios

## 4. ODT export

- [x] 4.1 Create `cvdoc/styles.py` with the `styles.xml` and the style names (`CvName`, `CvHeadline`, `CvContact`, `CvHeading`, `CvEntry` with a right tab stop, `CvLine`, `CvNote`, `CvSource`, list style `CvBullets`), and nothing about styling anywhere else; verify a test parses it as XML and lists the expected style names
- [x] 4.2 Create `cvdoc/odt.py` `write(cv) -> bytes` (design D7: `mimetype` first and stored, manifest, styles, content built with ElementTree, minimal meta, fixed timestamps); verify tests that `documents.odt_text` reads back the `Cv`'s text in order, that text with `<`, `&` and quotes survives, that every style used in `content.xml` is defined in `styles.xml`, and that two writes of the same `Cv` give identical bytes

## 5. Ranking (`tailor.py`)

- [x] 5.1 Create `tailor.py` with the constants (design D2), `METHOD = "cv-rank@1"`, and `Choice.from_args` (the only parser of the proposal's parameters: budget, counts, ticks, unticks, `tuned`); verify tests for defaults, out-of-range or non-numeric values falling back to defaults, and ids that don't exist being ignored
- [x] 5.2 Build candidates from `queries.profile`, dropping records whose effective disclosure is private and flagging highlights that mention a private record's title, organisation (4+ characters) or source address; verify tests for "Private record left out", "Private through its context" and "Highlight naming a private record"
- [x] 5.3 Implement values and the greedy highlight cover with `IRRELEVANT_COST`, ties, unticks and hand-ticks, reusing `recommend.py`'s weights and `queries.effective_links`; verify tests for "A posting skill counts once" (gain 2.55, then 0), "Covering what the posting doesn't ask for" (1.7 against 1.5), "Budget", "Missing skills show nothing", "Unticking the top highlight", and that an alias-linked posting skill counts
- [x] 5.4 Implement record selection by `KIND_RULES` (relevance summed per posting skill, filled by `record_sort_key`, printed in kind order, hand-ticks past the count) and course grouping; verify tests for "A relevant publication comes first", "Filling with the newest", "Projects by default" and "Raising a count"
- [x] 5.5 Implement details (`DEFAULT_DETAILS`), gaps (credit above 0, shown by no chosen highlight or record, with "covered by an unchosen highlight" or "no highlight covers it"), and `propose(conn, job_id, choice)` returning the content, the score and the per-item gains, relevance and flags; verify tests for "Default details", "A skill no highlight shows", "Shown by a record", "Skill the user lacks" and "Posting without skills", and that `propose` makes no writes (row counts of every table unchanged)

## 6. Saved CVs

- [x] 6.1 Add `userdata.save_tailored_cv`, `move_cv_item`, `remove_cv_item` and `delete_tailored_cv` (design D4); verify tests for "Profile edited after saving", "Two CVs for one posting", "Moving a highlight" (and no-op at the ends), removing a parent removes its children, and "Deleting a CV"
- [x] 6.2 Add `queries.tailored_cvs_for_posting` and `queries.tailored_cv` (items, posting title, company and URL, and items whose source is deleted or now private); verify tests for newest-first order, "Record made private after saving" and a deleted highlight being marked
- [x] 6.3 Verify "Re-capture after saving": a test re-imports a posting with a saved CV and a changed description, and the CV's rows are unchanged; and that accepting a document suggestion or editing the profile leaves them unchanged

## 7. Web interface

- [x] 7.1 Add `web/cvs.py` (registered in `create_app`) with the proposal page: `GET /postings/<job_id>/cv`, a GET form with htmx swapping the preview, gaps and choices, and `templates/cvs/proposal.html` and `_preview.html`; verify `tests/test_web_cvs.py` checks the page shows the score, the ticked items, the gaps and the preview, and that a GET writes nothing
- [x] 7.2 Add `POST /postings/<job_id>/cvs` (re-proposes from the posted choice inside the write transaction and saves; ignores private record ids) and the saved CV page `GET /cvs/<id>` with move, remove and delete actions and the deleted-since or private-since marks; verify tests for saving, each action with its 303 target, a 404 for an unknown CV, and the guard rejecting a POST with a foreign `Origin`
- [x] 7.3 Add `GET /cvs/<id>.odt` with the safe file name (design D7); verify a test checks the content type, the `Content-Disposition` name for a company and title with unsafe characters, and that the body reads back with `documents.odt_text`, and that no export link appears on an unsaved proposal
- [x] 7.4 Add the `cvs/_list.html` panel ("Tailor a CV" and saved CVs, newest first, each with date and score) to `postings/detail.html` and `applications/application.html`; verify the "Application page" scenario in a web test, and the posting page's original-posting link and other panels still render

## 8. Wrap-up

- [x] 8.1 Run `pytest`, and again with `JOBHUNT_TEST_PG_URL` set; verify everything passes on both
- [x] 8.2 Update CLAUDE.md: project status (this change; drafting and the other deferred items next), Architecture (`tailor.py`, `cvdoc/`, `web/cvs.py`), the user-authored table list, a "Tailored CVs" paragraph (ranking `cv-rank@1` and where its constants are, frozen snapshots, private records never printed, where to change styles and layout), and the downgrade note for `0009_tailored_cv`; verify the text matches what was built
- [x] 8.3 Run `openspec validate generate-tailored-cv --strict`; verify it passes

## 9. With the user

- [ ] 9.1 Ask the user to clean up the profile before the first real CV: the "March 2027" detail and the headline (design Context), the role's course-list lines, and the duplicated publication records; verify by opening a proposal on a real posting that the preview shows each item once
- [ ] 9.2 With the user, tailor and save a CV for a posting they choose, download it and open it in LibreOffice; record in design.md ("First CV") whether the selection was sensible, any highlights that `IRRELEVANT_COST` mis-ranked, and layout fixes wanted; verify any requested heading or style change is made in `layout.py` or `styles.py` only, and any ranking change becomes `cv-rank@2`
