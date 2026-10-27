## Context

See proposal.md for why, and specs/recommendations/spec.md for the behaviour. What the change builds on:

- `queries.posting_list` returns each posting's latest-snapshot `workplace_type`. Its value is `On-site`, `Hybrid`, `Remote`, or `None` when the header has no type. `queries.WORKPLACE_TYPES` lists the three types in that order.
- `recommend.recommendations(conn)` reads `posting_list(dismissed="included")` and ranks it with `rank_postings`. `rank_postings` drops dismissed, applied and skill-less postings. `skill_gains(ranked, …)` collects candidate keys, and (with `pool-unlinked-skills`) pools, only from the ranked postings. Narrowing the rows before ranking therefore narrows everything downstream.
- The Postings list's `ListFilters.workplace` is one string, used as a SQL `WHERE`.
- On Insights, "Have it" and "Don't have it" post to `/insights/skill`, which redirects to `safe_next(url_for("postings.insights"))`. A recommended profile skill's level form posts to `triage.set_level` with `next=/insights`. Neither form keeps a query string today. Both are htmx forms (`hx-target="main" hx-select="main"`), and htmx follows the 303.

## Goals / Non-Goals

**Goals:**
- Filter in Python on the rows `recommendations` already reads. No new query, and the filter means the same on Postgres and SQLite.
- One place decides what the URL values mean, tested without Flask.

**Non-Goals:**
- Making `ListFilters` multi-valued, or sharing a filter form between Postings and Insights.
- Changing any weight, score or pooling rule.

## Decisions

### D1. Parse in `recommend.py`; `None` means no filter

`recommend.workplace_choice(values: Iterable[str]) -> frozenset[str] | None` keeps the values that are in `WORKPLACE_TYPES` and returns `None` when that leaves none or all three. Otherwise it returns the chosen set. This is the only place that turns URL values into a choice, so "none ticked" and "all ticked" can't drift apart.

- **Why `None` rather than all three types:** the two differ for postings without a type, which are considered with no filter but left out of `{On-site, Hybrid, Remote}`. Normalising "all three" to `None` makes the default page and an all-ticked form give identical results. That is what the "Default is every posting" scenario requires.
- **Alternative:** a `ListFilters` field. Rejected: `ListFilters` is the Postings list's model, with a single-choice workplace field and a SQL translation. Insights never builds a list from the URL otherwise, and a second, multi-valued workplace field there would confuse both.

### D2. Narrow the rows before `rank_postings`

`recommendations(conn, workplaces=None)` drops rows whose `workplace_type` isn't in `workplaces`, when `workplaces` is set, before calling `rank_postings`. With that:
- `considered` and `no_skills` follow the filter;
- `skill_gains` sees only filtered postings, so gains, "Postings" counts, "Most improved" lists and pools (leaders and members) all come from them.

Posting skills, links, credits and stored vectors are still read for every posting. They are keyed by skill, not by posting, and `skill_gains` only looks up the keys it collects, so loading them unfiltered is correct and keeps the code simple.

The result gains `workplaces` (the chosen set, or `None`) for the template.

**Alternative:** filter in SQL through `posting_list`. Rejected: it would need a multi-valued `ListFilters` field (see D1) to save filtering a few dozen rows in Python.

### D3. The page passes its own URL as `next`

The `/insights` route reads `request.args.getlist("workplace")` and passes the result of `workplace_choice` to `recommendations`. It gives the template `here`: `url_for("postings.insights", workplace=sorted(chosen))` when a filter is set, else `url_for("postings.insights")`. Flask encodes a list as repeated `workplace=` parameters.

- The answer forms add `<input type="hidden" name="next" value="{{ here }}">`, and the level form's `next` becomes `here`. No route changes: `answer_skill` and `set_level` already redirect to `safe_next`.
- Building `here` from the parsed choice rather than `request.full_path` keeps unknown values and other parameters out of it. It also leaves no trailing `?`, and `safe_next` still checks it.

### D4. Filter form

The form is a GET form (`class="filters"`) above "Postings to look at first", with one checkbox per type, named `workplace`. A type is ticked when `r.workplaces` is `None` or contains it.
- With htmx, it uses `hx-get` to `/insights` with `hx-trigger="change"`, `hx-target="main" hx-select="main" hx-swap="outerHTML"` and `hx-push-url="true"`, so the URL is kept up to date.
- Without JavaScript, it uses a `<noscript>` Apply button, matching the level form.

The form only appears when there is something to recommend, inside the existing `{% else %}` branch.

### D5. Column and empty messages

- **Column:** a "Workplace" column goes after Company and shows `p.workplace_type or "—"`. The empty-row `colspan` goes from 5 to 6.
- **Empty messages:** when `r.workplaces` is set and `r.considered == 0`, each table's empty row says "No posting of the chosen workplace types is left to recommend." Otherwise the existing messages stay.
- **Skills table with postings left:** the skills table can be empty while postings remain (every asked skill already proficient). It then keeps its existing message.

## Risks / Trade-offs

- **Filtered skill lists draw on fewer postings.** With 6 On-site postings, an On-site-only skill list rests on a handful of postings, so its gains are noisy. → This is visible on the page: "Showing N of M" and each skill's "Postings" count say how many postings are behind it.
- **A posting's workplace type can change on re-capture.** → The filter uses the latest snapshot, like the Postings list and every other Insights field.
- **A posting with no type disappears as soon as any type is unticked.** → None does today. An "unknown" choice can be added later without changing anything else (proposal, "Not in this change").
- **Merge friction with `pool-unlinked-skills`.** It edits the same function and template. → Tasks start only after that change's code is committed.

## Migration Plan

None: no schema, data or setting changes. Rolling back is reverting the code; old `/insights?workplace=…` URLs then simply ignore the parameter.
