## Why

Insights ranks every posting together, so a user who only wants remote work (or wants to rule out on-site) can't see which postings to look at first, or which skills to learn, for the workplaces they would take. Each posting's workplace type (`On-site`, `Hybrid`, `Remote`) is already extracted from the posting's header and filterable on the Postings list. Insights doesn't show it or filter by it. On the user's database (2026-10-06), the 41 postings are 18 Hybrid, 17 Remote and 6 On-site, and none is missing a type.

## What Changes

- **A Workplace column** on "Postings to look at first", showing each posting's workplace type, or "—" when it has none.
- **A workplace filter on Insights:** one checkbox per type (`On-site`, `Hybrid`, `Remote`), all ticked by default. It narrows the postings that recommendations consider, so it applies to both tables:
  - Posting recommendations list only postings of the ticked types. "Showing N of M" and the count of postings without skills follow the filter.
  - Skill gains are summed only over those postings. For example, the skill list then answers "what would raise my matches for remote jobs". Pools of unlinked skills (`pool-unlinked-skills`) are formed from those postings' skills.
- **The filter is in the URL** (`/insights?workplace=Remote&workplace=Hybrid`), like the Postings list filters, so reloading or bookmarking keeps it. It isn't saved as a setting.
  - Ticking all three types, or none, means no filter. A posting with no workplace type is then included, and it is left out once the filter is narrowed.
  - Unknown values are ignored.
- **Answers keep the filter.** "Have it", "Don't have it" and a level change show the recommendations again under the same filter.
- **Empty filter result:** when no considered posting has a ticked type, both tables say so instead of their usual empty messages.

Not in this change:
- changing the Postings list's single-choice Workplace dropdown;
- filtering Insights by location, interest or anything else;
- an "unknown" checkbox (no current posting lacks a type).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `recommendations`:
  - "Posting recommendations" adds each posting's workplace type to what is shown.
  - A new requirement, "Workplace filter", narrows the postings that both posting and skill recommendations consider, and is kept across answers.

  "Skill recommendations" already sums over "the postings that posting recommendations would consider", so its text doesn't change. That also keeps this change clear of `pool-unlinked-skills`, which modifies that requirement.

## Impact

- `src/jobhunt/recommend.py`:
  - a pure parser from the query values to the chosen types (`None` for no filter);
  - a `workplaces` argument on `recommendations`, applied to the posting rows before `rank_postings`;
  - the chosen types in its result.
- `src/jobhunt/web/postings.py`: `/insights` reads `request.args.getlist("workplace")` and passes the page's own URL to the template as `next`.
- `src/jobhunt/web/templates/insights.html`:
  - the filter form;
  - the Workplace column;
  - `next` on the answer and level forms;
  - the empty-filter messages.
- Tests: `tests/test_recommend.py` (parser, and filtered recommendations from a database), `tests/test_web.py` (column, checkboxes, URL, filter kept after answering).
- No schema change, migration, setting, model request or dependency. `queries.posting_list` already returns `workplace_type`.
- Builds on `pool-unlinked-skills`, whose code is uncommitted in the working tree and touches the same files (`recommend.recommendations`, `insights.html`, `tests/test_recommend.py`, `tests/test_web.py`). Finish and commit that change first. The two modify different requirements of `recommendations`, so they can be archived in either order.
- Docs: CLAUDE.md, the "Match score and recommendations" bullet.
