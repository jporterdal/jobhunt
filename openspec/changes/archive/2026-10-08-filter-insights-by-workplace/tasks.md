## 0. Before starting

- [x] 0.1 Make sure `pool-unlinked-skills`'s code is finished and committed, so that `git status --short` lists no changes under `src/` or `tests/`. This change edits the same function, template and test files (see design, "Risks / Trade-offs"). Verify that `pytest tests/test_recommend.py tests/test_web.py` passes before any edit.

## 1. Filtering (`src/jobhunt/recommend.py`)

- [x] 1.1 Add `workplace_choice(values)` from D1. It keeps the values in `queries.WORKPLACE_TYPES` and returns a `frozenset`, or `None` when it keeps none or all three. Verify with tests in `tests/test_recommend.py`:
  - `[]` gives `None`;
  - all three types give `None`;
  - `["Remote", "Hybrid"]` gives that set;
  - `["Remote", "Moon"]` gives `{"Remote"}`;
  - `["Moon"]` gives `None`;
  - a repeated value is kept once.
- [x] 1.2 Give `recommendations` a `workplaces=None` argument (D2). It drops posting rows whose `workplace_type` isn't in the set before `rank_postings`, and returns `workplaces` in its result. Verify with database tests in `tests/test_recommend.py` on the synthetic postings (`BANK` On-site; `SIMILAR` and `AI` Hybrid), each with a profile skill and marks:
  - With `{"Hybrid"}`, `BANK` isn't recommended, and `considered` and `no_skills` count only Hybrid postings.
  - A skill marked only on `BANK` isn't a recommended skill under `{"Hybrid"}`, and is one with `None`.
  - A skill marked on `BANK` and `AI` improves 1 posting under `{"Hybrid"}` and 2 with `None`.
  - A posting re-captured with `workplace_type=None` (`add_posting(..., workplace_type=None)`) is considered with `None` and left out under `{"Hybrid"}`.
  - With `None`, the result equals today's: the existing tests pass unchanged.

## 2. Page

- [x] 2.1 In `web/postings.py`, have `/insights` read `request.args.getlist("workplace")` through `workplace_choice`, pass the result to `recommendations`, and pass `here` (D3) to the template. Verify with a `tests/test_web.py` test: `/insights?workplace=Hybrid` doesn't list `BANK` in `recommended-postings`, and `/insights?workplace=Moon` does.
- [x] 2.2 In `insights.html`:
  - add the filter form (D4), with three checkboxes named `workplace`, ticked when `r.workplaces` is `None` or contains the type;
  - add the Workplace column (D5), with the empty row's `colspan` raised to 6.

  Verify with `tests/test_web.py` tests:
  - the default page has all three boxes `checked`;
  - `?workplace=Hybrid&workplace=Remote` has `On-site` unchecked;
  - `BANK`'s row shows `On-site`;
  - a posting re-captured with no workplace type shows `—`.
- [x] 2.3 Keep the filter after answers (D3). Add `next` set to `here` to the "Have it" and "Don't have it" forms, and set the level form's `next` to `here`. Verify with `tests/test_web.py` tests:
  - posting "don't have it" with `next=/insights?workplace=Hybrid` redirects there;
  - the rendered answer forms on `/insights?workplace=Hybrid` carry that `next`;
  - a `next` of `//evil.example` still falls back to `/insights`.
- [x] 2.4 Add the empty-filter messages (D5). Verify with a `tests/test_web.py` test: with `BANK` dismissed, `/insights?workplace=On-site` shows "No posting of the chosen workplace types" in both tables, and the page without a filter doesn't.

## 3. Check and docs

- [x] 3.1 Check against the user's real database with a read-only connection and `create_app(..., ollama=None)`. Don't use `jobhunt serve`, don't trigger any model work, and confirm that the database file's checksum is unchanged. Render `/insights`, `?workplace=Remote` and `?workplace=Remote&workplace=Hybrid`, and report to the user:
  - `considered` for each;
  - the top 5 postings and top 5 skills of each.
- [x] 3.2 Update CLAUDE.md's "Match score and recommendations" bullet: the workplace filter narrows the considered postings for both lists, comes from the URL (none or all ticked means no filter), and isn't stored. Run `pytest`, `JOBHUNT_TEST_PG_URL=postgresql+psycopg:///jobhunt_test pytest` and `openspec validate filter-insights-by-workplace --strict`, and verify all pass.
