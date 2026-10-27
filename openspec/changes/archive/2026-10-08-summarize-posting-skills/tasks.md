## 1. Data

- [x] 1.1 Add `judged` to each `queries.effective_links` value (true when the key has a succeeded judgment); verify with tests in `tests/test_queries.py` or `tests/test_links.py` for a never-judged key, a key judged with no relation, and an override "no link"
- [x] 1.2 Add `recommend.best_option(options, levels)` and redefine `credit` through it (design, decision 1); verify the existing `tests/test_recommend.py` credit tests still pass, plus a new test that the "Best credit, not strongest relation" case returns `Large language models`
- [x] 1.3 Add `recommend.posting_summary(conn, job_id)` returning the score, the Have and Don't have entries grouped by importance and ordered as the spec says, the `missing`/`not-judged`/`no-link` reasons and `has_profile_skills`; verify with tests for each `recommendations` scenario ("Have and don't have" at 46%, "Credit from a weaker link", "Linked to a missing skill", "Not judged yet", a posting without skills) and one test that the summary score equals the posting's score from `recommend.recommendations`

## 2. Skill summary on the page

- [x] 2.1 Create `postings/_skill_summary.html` (`#skill-summary`: match line, Have and Don't have with Required / Preferred / Importance not set groups, `src-user`/`src-derived` items, profile links to `/profile#skill-<id>`, the empty-posting and empty-profile messages) and add its inline-list styles to `static/app.css`; verify by rendering in a `tests/test_web.py` test
- [x] 2.2 Pass `posting_summary` from `postings.detail_context` and include the fragment in `postings/detail.html` between the header row and `.grid2`; verify with a `tests/test_web.py` test that the detail page shows the score, a Have entry linking to its profile skill, and a Don't have entry with its reason

## 3. Collapsible "Skills asked for"

- [x] 3.1 Restructure `triage/_marks.html` as in design decision 5 (`#marks-panel` section, `#marks-heading` with the count and labelling status, the description from decision 7, a `<details>` without `open` holding `#marks`); verify with a `tests/test_web.py` test that the heading reads "Skills asked for (2 marked · labelling complete)" and "(none marked)", that the description is outside the `<details>`, and that the `<details>` has no `open` attribute
- [x] 3.2 Change the triage redirects (and any other `#marks` anchors) to `#marks-panel`; verify the existing redirect assertions are updated and pass
- [x] 3.3 Check that `static/marks.js` still highlights marks and opens the mark popup while the section is collapsed (it reads `#mark-quotes`, not the list); verify by marking a skill in the running app with the section collapsed

## 4. Refreshing the summary

- [x] 4.1 Add `#skill-summary` (and `#marks-heading` where marks change) to the `hx-select-oob` of the `action` macro in `llm/_panel.html` and of the importance, level and labelled forms in `_marks.html`; verify with tests in `tests/test_web.py` and `tests/test_web_llm.py` that the pages these actions redirect to contain the updated `#skill-summary` (a rejected suggestion leaves it, a level change moves a skill to Have)
- [x] 4.2 Make `llm.panel` append the summary fragment with `hx-swap-oob="true"`; verify with a `tests/test_web_llm.py` test that the panel response contains an out-of-band `#skill-summary` reflecting a just-finished run
- [x] 4.3 In the running app, expand "Skills asked for", change an importance and a level, and accept and reject a suggestion; verify the section stays expanded and the summary updates without a reload

## 5. Wrap-up

- [x] 5.1 Run `pytest` (and with `JOBHUNT_TEST_PG_URL` set if Postgres is available); verify everything passes
- [x] 5.2 Update CLAUDE.md's project status and the `recommend.py` line in Architecture to mention the posting-page skill summary; verify the text matches what was built
