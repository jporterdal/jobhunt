# Roadmap

Planned work, not yet proposed. Each item becomes an OpenSpec change (`openspec/changes/`) before it is built, and
model changes are measured before they are adopted (see `docs/measurement.md`). Nothing here is promised or ordered.

## Skill extraction measurement

- **Credit suggestions found on the same line.** The eval pairs a suggestion with a labelled mark only when their
  skill names match or their quotes overlap. The model sometimes finds the right skill on the right line but quotes
  different words ("Evals:" for a mark on "built eval"), so the mark counts as missed. Two options, which can be
  combined:
  - a same-line fallback in the eval only, which re-scores stored runs without calling a model, reported separately
    so before and after figures stay comparable;
  - keeping every location of a skill that the merge step drops as a duplicate, so matching can use any of them.

## Recommendations

- **A review list per skill.** Distinct unlinked posting skills, ranked by how many postings ask for them, each
  answered once ("I have it" with a level, "I don't", or "not a skill"). Today only the recommended skills can be
  answered, and there is no "not a skill" answer.
- **Show how much of a score is unresolved** ("0.42, 11 of 19 unresolved"), so a low score isn't confused with poor
  link coverage.
- **"Your CV doesn't say so."** Skills the user has and postings ask for, but no CV highlight shows, ranked by how many
  postings ask. The profile already flags claims without a highlight.
- **Better pools of unlinked skills.** Pooling by name similarity puts specific skills under generic leaders
  ("Unit testing" and "Fairness testing" under "Testing"). Measured rules (no name-containment joins for generic
  leaders, members broader than the leader never join, partial credit for narrower members) fix most of it but split
  some good pools. A model-judged pooler or hand corrections are the alternatives.
- **Later rounds:** weighting soft skills down, gating on degrees, explicit preferences (location, remote, salary),
  ordered sequences of skills to learn, and calibrating the weights in `recommend.py` from interest and fit ratings
  once there are enough of them.

## Skill linking

- **A combined shortlist.** Bare skill names miss concept-to-tool links ("Vector databases" to a specific vector
  store). Expanding skills into alternative phrasings finds them, but fills every shortlist and breaks correct
  refusals. The idea: keep the name shortlist and add only the best one or two candidates that expansion finds.
- **Flag a "no link" answer when the profile grows.** A refusal is a judgment against the profile of its day; mark it
  for review when a skill added since then joins its shortlist.
- **Show the judge the posting's line**, not only the quoted skill name, as a new judge version.
- **Simplify the relation set** (`same`, `specific`, `general`, `related`) if real use keeps blurring `general` and
  `related`.

## Reading CVs into the profile

- The skill step still suggests near-duplicates, paper and course titles, and fragments, which the user rejects or
  merges once. Prompt changes are a new step version, compared by hand until profile extraction has an eval.
- The same paper worded two ways (citation and title) becomes two records; merging records is left to the user.
