## Why

`restructure-profile-knowledge-base` turned the profile into a knowledge base (records, claims with grounds, highlights, details) so that a CV can be put together for each target job. The CV itself is still written by hand: the user picks which "Skills & Experience" lines and which publications or projects to show, and has no record of what was sent where. Now that every highlight says which claims it covers, and every posting skill links to profile skills, the app can propose the most relevant selection for a posting and keep a copy of each CV it produced.

## What Changes

- **Tailoring a CV for a posting.** A posting's page gains a "Tailor a CV" action. It opens a proposal that the app computes on each view, with no model calls and no writes:
  - **Highlights** are chosen within a budget (default 9) by a greedy weighted cover of the posting's skills. Each posting skill counts once, at its importance × relation × level, so a second highlight for the same skill adds nothing. A highlight also loses a little for each claim it covers that the posting doesn't ask for.
  - **Records** follow per-kind rules. Roles, courses, degrees and awards are always printed. Publications and projects are ranked by relevance, from the claims they ground, up to a count (default 3 publications, 0 projects). Events, tasks and other records are ranked with a default count of 0.
  - **Details**: name, headline, contact details and goal statements are included; summaries are left out by default.
  - The user can tick any highlight, record or detail in or out, change the budgets, and see a preview before saving.
  - The proposal lists **gaps**: posting skills the user has (credit > 0) that no chosen highlight or record shows, and states whether any highlight in the library covers them, so the user knows what to write.
- **Non-disclosure.** Records whose effective disclosure is private (themselves or through their `part_of` chain) are never offered or printed. A highlight whose text contains a private record's title, organisation or source address is flagged and left unticked by default.
- **Presentation rules.**
  - Sections follow a fixed order with headings by record kind.
  - Course terms of one course (same title and organisation) are condensed into one entry listing the terms.
  - A record printed along with its context record (`part_of`) appears under it, once. A record printed without its context says what it is part of.
  - The header prints the month the CV was produced.
- **Saved CVs are frozen snapshots.** Saving copies the chosen details, highlights and records, in order, with their text, into the user's tables. Later profile edits never change a saved CV. A saved CV can have items moved up or down, removed, or be deleted. It records the posting, the match score at the time and the ranking method (`cv-rank@1`). The posting page and the application page list the posting's saved CVs.
- **ODT export.** A saved CV downloads as an OpenDocument Text file, written with the Python standard library (no new dependency), to open and finish in LibreOffice or Word. The content model, the layout rules (section order, headings, date and term wording) and the ODF styles are separate modules, so the look can be changed later without touching selection or storage. The in-app preview renders the same content model as HTML.

### Deferred (later changes)

- Drafting new highlight wording with the model for gaps, and adding accepted drafts to the library.
- Checks on highlights that need more than text matching: a highlight naming a skill none of its claims is about, overstating a claim's level, flagging a highlight for review when a covered claim changes.
- A generated keyword list (needs a `category` on claims); a skill `kind` for weighting soft skills.
- Choosing description lines per job (lines of a printed record are always printed in this change).
- "N+ years" worked out from grounding records' dates.
- CVs for applications without a posting; cover letters; copying the styles of an uploaded CV.

## Capabilities

### New Capabilities
- `tailored-cv`: proposing a CV for a posting (highlight and record selection, details, gaps, non-disclosure), saving it as a frozen snapshot, editing and listing saved CVs, the presentation rules, the HTML preview and the ODT export.

### Modified Capabilities
<!-- none: the posting and application pages gain a panel, specified in `tailored-cv`; no existing requirement changes. -->

## Impact

- **Schema:** Alembic revision `0009` adds the user-authored tables `tailored_cvs` and `tailored_cv_items`. Its downgrade drops them, and with them every saved CV.
- **Code:**
  - new `tailor.py`: the proposal, read-only, reusing `recommend.py`'s weights and `queries` (`posting_skills`, `effective_links`, `profile`);
  - new `cvdoc/` package: `model.py` (content model and JSON), `layout.py` (sections, headings, dates, terms, nesting), `odt.py` (writer), `styles.py` (ODF styles);
  - `userdata.py`: saving, moving, removing and deleting CVs;
  - `queries.py`: saved CVs by posting, a saved CV;
  - `db.py`: tables and `USER_TABLES`;
  - new `web/cvs.py` with its templates; panels on `postings/detail.html` and `applications/application.html`.
- **Tests:** new `test_tailor.py`, `test_cvdoc.py` (layout and ODT, read back with `documents.odt_text`), `test_web_cvs.py`; `test_migrate.py` covers the new revision.
- **Model use:** none.
- **Data:** the generator prints what the knowledge base holds. Before the first real CV, the user cleans up a few things on the profile page: the "March 2027" and headline details left over from the upgrade, the role's course-list lines (repeated by the course records), and duplicated publication records.
- **Docs:** CLAUDE.md (project status, architecture, data kinds, backups and downgrade note). `HANDOFF.md` §6 is folded into design.md, so the knowledge-base change's task 11.4 can delete `HANDOFF.md`.
- **Order:** archive `restructure-profile-knowledge-base` before this change. No delta here touches its specs.
