## Context

See proposal.md for why. What the change builds on:

- `queries.posting_skills` gives every posting's skills (marks, plus the verified, unrejected suggestions of its latest app run), each `required` or `preferred`.
- `queries.effective_links` gives one link per posting key: the override, else a same-key profile skill, else the strongest relation of the latest judgment to a profile skill. It reads all the judgment's relations but keeps only one.
- `skills.level` is the profile. `missing` is already the lowest level on the scale, and `userdata.add_profile_skill(name, level)` already creates a skill by name and gives it a level. That's enough for "don't have it", but today the user can only set levels on skills that have a `skills` row, which in practice means marks. About 82% of posting skills are suggestions only.
- Adding a profile skill calls `userdata.skills_changed`, which queues link judging. The plan then re-judges every key whose shortlist changed, so a new `missing` skill becomes a candidate for its variants without new code.
- `/insights` is a placeholder page in `web/postings.py`.
- Data on 2026-10-06:
  - 40 postings with skills, 17–87 skills each
  - 81 profile skills, all levels set by the model, none at `missing`
  - no interest ratings, dismissals or applications

## Goals / Non-Goals

**Goals:**
- The scoring is plain arithmetic in one module, tested without a database or Flask, with all weights in one place so they can be tuned later.
- No new tables, migration or settings, and no model requests when the page is computed.

**Non-Goals:**
- Storing scores, or an `analyses` table.
- Measuring the ranking. There are no ratings yet to measure it against.
- Changing how links are judged or shown.

## Decisions

### D1. `recommend.py`: pure functions plus one loader

`src/jobhunt/recommend.py` has three parts:
- **Constants:** `RELATION_WEIGHT`, `LEVEL_WEIGHT`, `IMPORTANCE_WEIGHT`, `HAVE_LEVEL = "proficient"`, `TOP_POSTINGS = 20`, `TOP_SKILLS = 15`.
- **Pure functions:** `credit(options, levels)`, `score(skills, credits)` and `skill_gains(...)`. They work on plain dicts.
- **`recommendations(conn)`:** loads data through `queries` (posting skills, link options, profile levels, triage, dismissals, applications, titles) and returns the two lists for the template.

The module has no Flask code and doesn't write. *Alternative:* put it all in `queries.py`. That file is already over 1,000 lines, and the scoring is logic, not a read model.

### D2. Link options come from `effective_links`

Each value `effective_links` returns gains an `options` list of `(skill_id, relation)`, which is every link the credit may come from:
- an override: its one link, or none for "no link"
- a same-key profile skill: one `same` link
- a model judgment: every usable relation of the latest judgment

The returned `skill_id`/`relation` stay as they are, so the links page and linking are unchanged. *Alternative:* a separate `link_options` function. It would repeat the override and same-key order, and the two could drift apart.

### D3. Best credit, not strongest relation

Strongest relation is right for showing one link. It is wrong for scoring once `missing` skills exist: a `same` link to a `missing` skill would hide a `related` link to a skill the user has. A credit is relation weight × level weight, and the highest credit over the options counts.

### D4. Weights

- **Relation:** `same` and `specific` are 1.0, because a specific form of what's asked (GitHub Actions for CI/CD) meets the ask. `general` is 0.6 and `related` is 0.3.
- **Level:** `missing` 0, `learning` 0.25, `familiar` 0.5, `proficient` 0.85, `expert` 1.0. `proficient` is below 1 so `expert` still counts for something.
- **Importance:** required 2, preferred 1.

These are guesses meant to be tuned once there are ratings. `posting_triage.fit` could calibrate them later.

### D5. Gain is "what if I had it at `proficient`", summed over postings

- For each candidate, every affected posting's score is recomputed with the candidate changed. For an unlinked key, that key gets credit 0.85 (`same` × `proficient`). For a profile skill, its level becomes `proficient` and the credits of its linked posting skills are recomputed through D3.
- Gain is Σ (new score − old score) × interest factor over the postings that posting recommendations would consider. It is shown ×100, as percentage points.
- Cost: about 600 candidates, each recomputing only the postings that ask for it, which is instant at this size.
- Unlinked keys are candidates by key, so variants (`Azure`, `Azure OpenAI`) count separately until the user answers "don't have it" for one and link judging groups the others under it. That is why the "missing" answer is part of this change.
- *Alternative:* count the postings that cross a match threshold. With 17–87 skills per posting, one skill rarely moves a posting across a line, so most gains would be zero.
- *Alternative:* make posting skills linked only weakly (`related`) candidates too. Left out to keep candidates from repeating each other. A profile skill below `proficient` already covers part of this.

### D6. Interest factor is `interest / 3`

- An unrated posting counts as 3, so the factor runs from 0.33 to 1.67, and with no ratings the ranking is match alone.
- `fit` is not used: it is the user's own judgment of match, which the score is trying to estimate, so using it would be circular.
- Dismissed postings and postings with an application are excluded from both posting recommendations and skill gains: they are decided.

### D7. Answering a skill

- The Insights page lists skill candidates.
- **Unlinked key:** the row has a level `<select>` (`learning`…`expert`) with a "Have it" button, and a "Don't have it" button.
  - Both post the skill's display name and the level to a new `POST /insights/skill` in `web/postings.py`.
  - The route calls `userdata.add_profile_skill(name, level)` in a write transaction and redirects to `/insights`, matching the `safe_next` pattern.
  - `add_profile_skill` creates the `skills` row when the key is a suggestion only. Its key equals the posting key because both come from `userdata.name_key`, so the next page load links it as `same`.
- **Profile skill:** the row has the same level `<select>` the skills page uses, posting to the existing `triage.set_level` with `next=/insights`.
- The route rejects levels outside `SKILL_LEVELS` and blank names through `UserDataError`, as the other routes do.

### D8. Insights replaces its placeholder

- `/insights` keeps its address and its place in the navigation.
- The template shows two tables, postings then skills. When there is nothing to recommend, it shows the empty state the spec describes.
- Every posting row shows its detail link and its original-posting link, using the `original_link` macro in `templates/macros.html`.

## Risks / Trade-offs

- **Variant names split demand** (`Azure` 15, `Azure OpenAI` 6, `Azure ML` 5) until the user answers "don't have it" and links are judged again. → The answer is one click on the page that shows the problem. Grouping needs the link-judging job to run, which needs Ollama and a chat model.
- **Common soft skills dilute every score.** For example, `Communication` is in 27 postings. → Accepted for now. Down-weighting by kind is a later round: posting skills from marks have no kind, so it needs more than a constant.
- **Model-set levels are almost all `proficient`**, so "improve" gains are small and rest on the model's reading of the CV. → Gains from unlinked and `missing` skills dominate, which matches what the user asked for. Levels can be corrected on the skills or profile page.
- **Skills the user has but the profile lacks** come up as "learn this". → "Have it" on the same row fixes them at once.
- **`missing` skills appear in the profile's skills panel**, grouped under `missing`. → That is already how the profile groups levels. Any later CV generation must leave `missing` and `learning` skills out.
- **Answering queues link judging**, which uses the GPU when the worker runs. → This is existing behaviour for any profile change. It is coalesced into one queued job, and the page itself makes no model calls.
- **Cost per page load** is `posting_skills` over all postings (about 1,700 rows) plus `effective_links`. → Fine at this size. Cache it if it ever becomes slow.

## Migration Plan

No schema change. Deploying is the code change. Rolling back is reverting it. Profile skills added through answers stay as ordinary user-set profile skills.
