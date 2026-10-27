## Why

A posting's page never says which of its skills the user has. The match score and its links are only visible on Insights (as a percentage, a count of unlinked skills and three gaps) and on `/profile/links` (every posting skill of every posting, about 840 rows). Meanwhile the "Skills asked for" panel shows a long list of controls (importance, level, remove) for each mark, which is only needed while labelling. Postings ask for 10 to 87 skills (median about 33) on the user's data (2026-10-07), so the page needs a short answer first and the controls only on request.

## What Changes

- **A skill summary on the posting page**, full width between the page header and the two columns:
  - the posting's match score as a whole percentage, the same number Insights shows;
  - **Have**: the posting skills that earn credit from the profile. Each shows the profile skill the credit comes from (a link to it on `/profile`), the relation and the user's level, e.g. "Kubernetes → Docker (related, familiar)";
  - **Don't have**: the posting skills that earn no credit, each with why: no link; linked only to profile skills at `missing` (named, with a link to them on `/profile`); or not judged yet;
  - both lists split into required and preferred (and "importance not set" for marks without one). Unaccepted model suggestions are included, as in the match score, and styled as model-derived; marks are styled as the user's.
- **"Skills asked for" collapses.** It stays where it is (last panel of the right column):
  - its heading carries the number of marks and the labelling status, e.g. "Skills asked for (12 marked · labelling complete)";
  - a short description (four sentences) under the heading says what the panel holds, where unaccepted suggestions are accepted ("Model says"), and what importance and level mean. The heading and description are always visible;
  - the list of marks with its controls, and the "Labelling complete" button, sit in a collapsed section below them. It is collapsed whenever the page loads, and stays as it is (open or closed) while the user changes something inside it.
- **The summary stays current.** Every action on the page that changes the posting's skills or a level (accepting or rejecting suggestions, undoing a rejection, changing importance or level, removing a mark) refreshes the summary along with its own panel, and so does the "Model says" panel when a run finishes.

Not in this change:
- changing links from the posting page (they are still changed on `/profile/links`);
- changing how the level control in "Skills asked for" behaves;
- changing "Model says", Insights, the match score or its weights;
- refreshing the summary when a background link-judging job finishes (a reload shows it).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `recommendations`: a new requirement, "Skill summary on the posting page", shows the match score and the Have / Don't have lists for one posting, using the existing skill credit.
- `posting-triage`: a new requirement, "Skills asked for panel", makes the marks panel collapsible with an always-visible heading and description.

## Impact

- `src/jobhunt/recommend.py`: a per-posting summary built from the existing `credit` and `score`, naming the option each credit comes from.
- `src/jobhunt/queries.py`: `effective_links` also reports whether a posting key has a succeeded judgment, to tell "not judged yet" from "no link".
- `src/jobhunt/web/postings.py` (`detail_context`), `web/llm.py` (`panel`): the summary in the page and in the panel's polling response.
- Templates: `postings/detail.html`, a new summary fragment, `triage/_marks.html`, `llm/_panel.html` (the out-of-band summary refresh); `static/app.css`.
- Tests: `test_recommend.py`, `test_queries.py`, `test_web.py`, `test_web_llm.py`.
- No schema change, no new dependency, no model request.
