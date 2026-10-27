## 1. Link options

- [x] 1.1 In `queries.effective_links`, add `options` (a list of `{skill_id, relation}`) to every value, built in the D2 order:
  - an override's single link, or `[]` for "no link"
  - a same-key profile skill's `same` link
  - every usable relation of the latest judgment

  The existing fields stay unchanged. Verify with a new test in `tests/test_links.py`: a judgment relating two profile skills gives both options while `relation` stays the strongest. Check that the existing link tests pass unchanged.

## 2. Scoring (`src/jobhunt/recommend.py`)

- [x] 2.1 Add the D1 constants and `credit(options, levels)`: the best relation weight × level weight, 0 with no options. Verify with `tests/test_recommend.py` covering the spec's "Same skill at a level", "Best credit, not strongest relation" (0.255) and "No link" scenarios.
- [x] 2.2 Add `score(skills, credits)`: the importance-weighted average, plus the count of skills with no options and up to three gaps (the most weighted credit lost, required first). Verify with the "Three skills" scenario (0.46, 1 of 3 unlinked) and a posting with no skills (no score).
- [x] 2.3 Add posting ranking: score × `interest / 3` (unrated counts as 3), ties broken by last seen, newest first. Exclude dismissed postings, postings with an application, and postings with no score, and count those with no skills. Verify with the "Interest lifts a posting" and "Dismissed and applied postings" scenarios.
- [x] 2.4 Add `skill_gains`, which builds the D5 candidates:
  - unlinked keys, set to credit 0.85
  - profile skills below `proficient`, with their level raised to `proficient` and their linked posting skills' credits recomputed

  Gain is the summed score rise × interest factor over the considered postings. Drop zero gains, keep the top 15, and record the improved postings, most improved first, up to five. Verify with the "Asked for more often" (+68 vs +20), "Variants grouped under a missing skill" and "Skill already proficient" scenarios.
- [x] 2.5 Add `recommendations(conn)`, which loads everything through `queries` and returns both lists, plus the empty-state flags (no posting skills, no profile skills). Verify with a database test using `tests/conftest.py` fixtures: two postings, marks and a judgment give the expected order. Also check that computing writes nothing, by comparing table row counts before and after.

## 3. Insights page and answers

- [x] 3.1 Replace the `/insights` placeholder with a page that renders `recommend.recommendations` and has two tables:
  - **Postings:** title, linked to the detail page; company; score %; unlinked count; gaps; the `original_link` macro link
  - **Skills:** name; current level for profile skills; gain; posting count; up to five postings

  It also needs the two empty states. Replace `test_insights_placeholder` in `tests/test_web.py` with tests for both tables and the "Empty profile" state.
- [x] 3.2 Add `POST /insights/skill` (name, level), which calls `userdata.add_profile_skill` and redirects to `/insights`. Rows for unlinked keys get a "Have it" level select (`learning`…`expert`) and a "Don't have it" button (`missing`). Rows for profile skills get the existing `triage.set_level` select, with `next` set to `/insights`. Verify with web tests:
  - "don't have it" on a suggestion-only skill creates a `skills` row at `missing` with `level_origin='user'`, and queues a links job when a chat model is set
  - "have it" at `familiar` gives that key credit 0.5 on the next load
  - an unknown level is rejected
  - the guard rejects a cross-origin POST
- [x] 3.3 Check the page against the user's real database (`jobhunt serve`, read only, with no answers given): both tables render, and the top unlinked skills include AWS, Azure and Kubernetes. Report the top 5 postings and the top 10 skills to the user. Don't trigger any model work.

## 4. Docs and checks

- [x] 4.1 Update CLAUDE.md:
  - **Project status:** `add-recommendations` added the match score, posting and skill recommendations on Insights, and the "have it"/"don't have it" answers. Drop "Scoring postings against the profile (`add-skill-match`) … still open".
  - **Architecture:** add `recommend.py`.
  - **Profile section:** add a line on how credits are computed (best credit over link options) and where the weights live.

  Verify by reading the diff.
- [x] 4.2 Update FUTURE_CHANGE.md item 2 ("Notes for `add-skill-match`"):
  - mark the parts this change delivered ("missing" as a profile level used by scoring)
  - keep the open ones (per-skill review list, unresolved share, relation set, rating data)
  - add the later rounds listed in the proposal

  Verify by reading the diff.
- [x] 4.3 Run `pytest` and, when `JOBHUNT_TEST_PG_URL` is available, `JOBHUNT_TEST_PG_URL=postgresql+psycopg:///jobhunt_test pytest`. Both pass. Run `openspec validate add-recommendations --strict`, which passes.
