## Why

The app collects postings, extracts their skills, keeps the user's profile and links the two, but it doesn't yet answer the two questions all of that is for: which postings should I look at first, and which skill should I learn next? Everything needed for a first answer is already stored, so a small change can give both, to be improved later.

## What Changes

- **A match score per posting.** Each skill a posting asks for earns credit from the user's profile: the relation of its link (`same`/`specific` 1.0, `general` 0.6, `related` 0.3) times the level of the linked profile skill (`missing` 0 up to `expert` 1.0). The best credit over the skill's links counts. The score is the posting's average credit, with required skills counting twice as much as preferred ones. The weights are constants in one place.
- **Posting recommendations.** Postings ranked by match score times a factor from the user's interest rating (unrated is neutral). Dismissed postings and postings with an application are left out. Each row shows the score, how many of its skills have no link, its largest gaps, and its original-posting link.
- **Skill recommendations.** For each candidate skill, the app works out how much the scores would rise, weighted by interest, if the user had it at `proficient`. Candidates are posting skills with no link, and profile skills below `proficient` (the latter includes `missing` ones). The top 15 are shown, each with the postings it would improve.
- **"Have it" and "don't have it" for any posting skill.** On each recommended skill without a link, the user can answer "have it" (with a level) or "don't have it". Both add the skill to the profile; "don't have it" adds it at `missing`. This works for skills only the model suggested, which have no level controls today. A `missing` skill earns no credit, but it becomes a link target, so variants of it (`Azure OpenAI` → `Azure`) are grouped under it in skill recommendations once links are judged again.
- **The Insights page shows the recommendations**, replacing its "no analyses yet" placeholder.
- Recommendations are computed when the page is opened, from stored data. Nothing new is stored and no model requests are made. Answering a skill changes the profile, which queues link judging, as any profile change does today.

Not in this change, for later rounds: a per-skill review list over every unlinked skill, a "not a skill" answer, weighting soft skills down, gating on degrees, explicit preferences (location, remote, salary), ordered sequences of skills to learn, and the gaps where the user has a skill that the CV doesn't show.

## Capabilities

### New Capabilities
- `recommendations`: the match score, posting recommendations, skill recommendations, and answering "have it" or "don't have it" for a recommended skill.

### Modified Capabilities
- `web-interface`: the Insights section shows the recommendations instead of a placeholder.

## Impact

- New `src/jobhunt/recommend.py` (pure Python, no Flask): credits, scores, gains.
- `queries.effective_links` also returns every usable relation of a posting skill (its link options), so scoring can take the best credit; the link it shows is unchanged.
- `web/postings.py` (`/insights`) and `templates/insights.html`; an answer route that calls the existing `userdata.add_profile_skill`.
- No schema change, no migration, no new settings, no new dependency.
- Supersedes the `add-skill-match` change planned in the archived `add-cv-skill-profile` proposal and FUTURE_CHANGE.md item 2: this is its first, smaller version.
