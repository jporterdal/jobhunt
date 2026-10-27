## Context

See proposal.md for motivation. Current state that shapes the approach:

- The match score and credits live in `recommend.py` (`credit`, `score`), computed on each view from `queries.posting_skills` (marks plus unrejected verified suggestions of the latest app run) and `queries.effective_links` (each key's shown link and its credit `options`). Insights calls them for every posting at once; nothing is stored.
- `effective_links` gives `source=None` both for a key whose latest succeeded judgment found no usable relation and for a key never judged, so "no link" and "not judged yet" can't be told apart today.
- Posting-page actions in "Model says" (`llm/_panel.html`, the `action` macro) and in "Skills asked for" (`triage/_marks.html`) post, get a 303 to the detail page, and htmx picks `#model-says` and/or `#marks` out of the full page with `hx-select`/`hx-select-oob`. The "Model says" panel polls `GET /llm/panel/<job_id>` every 3 s while its job is active, and that route renders only `llm/_panel.html`.
- `/profile` gives every profile skill an anchor, `#skill-<id>`.
- The web UI has no JavaScript build step. `marks.js` handles highlighting and the mark popup and doesn't depend on the marks list being visible.

## Goals / Non-Goals

**Goals:**
- Posting-page numbers that always equal Insights' for the same posting.
- No new JavaScript. Collapsing uses native `<details>`.
- One extra query per page view at most; no model requests.

**Non-Goals:**
- Live refresh when a background links job finishes.
- Remembering whether the section was open across page loads.
- Any change to `recommend.recommendations` or its output.

## Decisions

**1. The summary is built in `recommend.py` from the existing credit code.** Add `best_option(options, levels)`: the option with the highest credit, the first on a tie, or None. `credit` becomes its credit, so the two can't drift apart. Add `posting_summary(conn, job_id)`, which returns:
- `score`: from `score()`, for the score and the unlinked count;
- `have`: entries with the posting skill (name, key, importance, source), the credit-giving profile skill (id, name, level), the relation and the credit;
- `dont_have`: entries with a `reason` of `missing` (plus the shown link's profile skill), `not-judged` or `no-link`;
- `has_profile_skills`.

The entries are grouped by importance (`required`, `preferred`, None). *Alternative:* compute it in `queries.py` or the template. Rejected because the credit rules would then exist twice.

**2. `effective_links` reports `judged`.** Each value gains `judged: bool`, which is true when the key has a succeeded judgment (it already loads `latest_judgments`). "Not judged yet" means no options, no override and `judged` false. A key with a same-key profile skill always has options, so it never reaches this check. Existing callers ignore the new field. *Alternative:* a separate query in `posting_summary`. Rejected because it would read the judgments twice.

**3. Placement and fragment.** A new `postings/_skill_summary.html` renders `<section class="panel" id="skill-summary">`. `detail.html` includes it between the header row and `.grid2`. The section contains:
- a line "Skill match 46% · 1 of 3 skills without a link", following the wording of the "Posting match score" requirement;
- "Have (n)" and "Don't have (n)", each with its "Required", "Preferred" and "Importance not set" groups as inline lists, so 50 names take a few lines rather than 50 rows.

Each item is an `<li>` with `src-user` (from a mark) or `src-derived` (from a suggestion). Formats:
- Have: `Kubernetes → <a href="/profile#skill-12">Docker</a> (related, familiar)`. With the same key: `<a …>Python</a> (same, proficient)`.
- Don't have: `Kubernetes — missing: <a …>Kubernetes</a>`, `Terraform — not judged yet`, `AWS — no link`.

**4. Refreshing the summary by reusing the redirect-and-select pattern.** The actions already answer with the full detail page, so the summary only needs to be listed in `hx-select-oob`:
- the `action` macro in `llm/_panel.html` always selects `#skill-summary` out of band, and with `marks=True` also `#marks` and `#marks-heading`;
- the importance, level and labelled forms in `_marks.html` add `#skill-summary,#marks-heading` to their out-of-band selection.

`llm.panel` (the polling route) appends the summary fragment with `hx-swap-oob="true"`, so it refreshes on every poll, including the one that shows the finished run. The cost is one posting's summary every 3 s while a job runs. *Alternative:* add the summary only once the job is no longer active. Rejected: it saves little and adds a state check.

**5. Collapsing with native `<details>` that is never swapped.** The structure of `_marks.html` becomes:

```
<section class="panel src-user" id="marks-panel">
  <h2 id="marks-heading">Skills asked for (12 marked · labelling complete)</h2>
  <p class="small muted">…description…</p>
  <details>                      <- no `open`: collapsed on every load
    <summary>Show marks and options</summary>
    <div id="marks"> …mark list, "Labelling complete" form… </div>
  </details>
</section>
```

htmx swaps only `#marks` (inside the `<details>`) and `#marks-heading`, so the `<details>` element and its open state survive every action. The heading reads "(n marked)", "(1 marked)" or "(none marked)", with " · labelling complete" when the flag is set. *Alternatives:* swap the whole section and restore `open` with a script, or use `hx-preserve`. The first is new JavaScript; the second would freeze content that has to change.

**6. Redirect anchors point at the section, not the list.** The triage routes redirect to `#marks`, and the posting page's full-page mark form ends there too. Browsers that open a `<details>` for a fragment inside it would then show the section expanded on load. These anchors become `#marks-panel`. With htmx the anchor is irrelevant. Without JavaScript the page loads collapsed, as the spec requires.

**7. The description's wording:**

> Your marks on this posting: text you selected in the description, or suggestions you accepted. Suggestions you haven't accepted are in “Model says”, below the description, where you can accept or reject them. Importance is for this posting only. Level is your level for the skill under this name wherever it's marked: setting one adds the skill to your profile and clearing it removes it; to change the level of a profile skill a link points to, follow its link under “Have”.

## Risks / Trade-offs

- [A new mark shows "not judged yet" until the links job runs and the page is reloaded] → The label says why. A live refresh for links jobs is a non-goal.
- [The summary pushes the description down on postings with many skills] → Inline lists per group. The user chose the full-width placement knowing this.
- [Recomputing on every poll] → One posting's skills, links and profile. The page view already does the same work.
- [Insights and the posting page could disagree if one stops using `credit`/`score`] → Both call the same functions. A test checks that a posting's summary score equals its Insights score.

## Migration Plan

No schema change and no data change. Rolling back means reverting the code.
