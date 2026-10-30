# Measuring the models

Model output in jobhunt is a suggestion, and every suggestion is checked against the text it claims to quote. That
makes the output safe to show. It doesn't make it good, so each model step is measured against the user's own labels
before a new version replaces the old one. This page describes the method and its headline results. The full
write-ups, with every table, are in the archived changes linked below.

## Skill extraction

**Labels.** The user labels 5–10 postings *before* extracting them: every skill the posting asks for is selected in
the text and marked required or preferred, then the posting is flagged "labelling complete". A skill the user only
noticed because the model suggested it is *accepted*, not selected by hand, since selecting it after seeing the
suggestion would flatter the model. When a posting is first flagged, it is drawn into the *dev* or the *holdout* set
(or the user chooses one), so prompts tuned on the dev postings are also checked on postings they never saw. The
draw aims for a holdout share (0.5 by default): the odds of holdout multiply by e for each posting it falls short and
divide by e for each posting it is ahead. A posting keeps its set; a holdout posting can be moved to dev, never back.
The report shows dev, holdout and both together, and the drawn holdout postings alone when some were chosen or moved.

**Scoring by mark origin** (`jobhunt eval`):

- *Recall* counts only the marks the user selected unaided.
- *Precision* counts a suggestion right when it matches any mark, wrong when the user rejected it, and leaves the
  rest out as *unjudged*, reported beside it. A rejection carries a reason ("not a skill" or "not for me"), and the
  report breaks wrong suggestions down by reason.
- Marks are placed at every whole-word occurrence of their quote. Each miss is attributed to segmentation,
  extraction, or a quote that couldn't be located.

**Windows** (`jobhunt eval --posted-within 12m --labelled-within 6m`). To see whether recent postings, or recently
labelled ones, score differently from the whole set, a window reports each set's figures for the postings posted, or
last flagged complete, within an age of now, beside the figures for all postings. A posting without a posted date
counts from the day it was first seen, and relabelling a posting moves it into the labelled window. A window changes
nothing that is run, scored or stored, and never moves a posting between dev and holdout. The windowed figures come
from a handful of postings and are for diagnosis: adopting or deleting a method uses the figures for all postings, and
the report says so.

**Results.** On 9 labelled postings, the app's prompt (`atomic@2`) found 91 of 102 selected marks, and 103 of its
311 suggestions were rejected. Two stricter prompts cut the rejected suggestions to 24 of 163 and 28 of 178, but
lost 14–15 marks of recall. The marks they lost were expertise worded as work, broad disciplines, and skills on
lines that also held excluded items. Each revision moved recall by about one mark while changing *which* marks were
found: a 12B model follows a prompt's wording more than its rules, and 9 postings can't tell the two apart. The
original prompt stayed the default, and the stricter one was deleted.
([tighten-skill-definition](../openspec/changes/archive/2026-10-05-tighten-skill-definition/design.md),
[improve-skill-extraction](../openspec/changes/archive/2026-10-04-improve-skill-extraction/design.md),
[accumulate-extraction-feedback](../openspec/changes/archive/2026-10-05-accumulate-extraction-feedback/design.md))

**Placement is part of the measurement.** The validator used to store a quote at its first substring match, so a
short name like "CI" could land inside "Specific". The suggestion was then highlighted in the wrong place, and the
eval couldn't pair it with the user's mark. Placing quotes on whole words first (`v@3`) fixed the one misplaced span
and moved recall from 90 to 91 of 102, with no model calls needed to predict it.
([locate-quotes-on-whole-words](../openspec/changes/archive/2026-10-05-locate-quotes-on-whole-words/design.md))

## Skill linking

A posting skill is linked to a profile skill in three steps. A shortlist comes from embedding similarity (bare
names, cosine ≥ 0.75, at most 5). A judge model then picks a relation for each shortlisted skill: `same`,
`specific`, `general`, `related` or none. The user's own overrides always win.

**Reference set.** The user's overrides: links they set by hand, and "no link" answers. At the end of the
measurement the set held 52 links and 27 refusals.

**Paired verdict** (`jobhunt eval --links`). Two methods are compared posting skill by posting skill. A skill counts
as right under a method if its link is right or a refusal is kept. The report counts the skills one method fixes
and the other breaks, and applies a one-sided exact sign test. The verdict is `better` or `worse` only at p ≤ 0.05,
and otherwise `within noise`. Judging the same skill twice flips a few answers, so differences of 2–4 links are
noise on a set this size.

**Results** (against the app's method, bare names with `link-judge@5`, which got 21 of 52 links right and kept 27
of 27 refusals):

| Method | Fixed | Broke | Verdict |
|---|---|---|---|
| Judge `@2` (examples drawn from the reference set) | 3 | 1 | within noise |
| Judge `@6` (shows the CV line, not only the quote) | 2 | 4 | within noise |
| Shortlist from expanded phrasings (`skill-expand@1`) | 10 | 18 | within noise (p=0.09) |
| Shortlist trimmed to matched phrases | 2 | 9 | worse |

- `@2` scored best, but two of its examples were links from the reference set itself. Replacing just those two
  examples lost those exact links. `@5`, which is `@2` with neutral examples, became the app's judge: its figures
  aren't inflated by examples taken from what it is measured against.
- Expanding skills into alternative phrasings found the concept-to-tool links that bare names miss, such as a
  general technique to a specific library. But it filled every shortlist, and the judge then found weak `general`
  links where the user had said "no link". It stays registered for measuring only.

([improve-skill-linking](../openspec/changes/archive/2026-10-06-improve-skill-linking/design.md))

## Rules that came out of this

- A step whose output changes gets a new version, so runs from different versions are never compared as equal.
- A candidate is adopted only on a `better` verdict, or with the user's explicit agreement and the reason recorded.
  A candidate that isn't adopted is deleted, so at most one candidate per step sits beside the app's method.
- Eval runs are stored apart from app runs (`origin`), so measuring never changes what the app shows.
- Examples in a prompt never come from the data the prompt is measured against.

## Known limits

- The labelled set is small (9 development postings when these figures were taken). Most differences between
  prompts are within noise.
- The link reference set is one person's links, and the shortlist floor is tuned on one profile.
- The judge is stricter than the user on `general` and `related`.
- A "no link" answer isn't flagged for review when the profile later gains a candidate.
