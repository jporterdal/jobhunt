## Why

The validator stores each verified quote at its first substring match. On posting A the model suggested `CI` from the line "Specific tooling: Git, CI, containers…", and the span was stored inside "Spe**ci**fic". As a result, the UI highlights the wrong text and the eval can't pair the suggestion with the user's `CI/CD` mark, so it counts as an extraction miss. This is the only misplaced span among the 311 verified suggestions in the current `@2` runs, but short names (`R`, `Go`, `C`, `AI`, `ML`) will keep hitting it. The eval already places marks by whole word (`evaluate.placements`). The validator should follow the same rule.

## What Changes

- **Whole-word location for verified quotes.** The validator places a quote at its first *whole-word* occurrence. If there is none, it falls back to the first plain substring match, so a partial-word quote still verifies. A match counts as whole-word under the eval's existing rule: only the quote's own first and last characters are checked, so `C#`, `C++` and `.NET` still match next to punctuation.
- **Search order is unchanged.** The validator looks in the item's source line first, then in the whole text. The whole-word preference applies within each of those searches. A whole-word match elsewhere in the text does not override a partial-word match on the source line.
- **Verification is unchanged.** Whether a quote counts as verified still depends only on whether it occurs at all. This change affects only *where* a verified quote is stored. The same applies to salary quotes, which use the same locator.
- **One rule, one place.** The whole-word rule moves into `validate.py`, and `evaluate.placements` uses it from there.
- **Validator bumps to `v@3`.** The pipeline id becomes `seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3`.

Out of scope:
- Re-validating stored runs without the model. A new pipeline id means new runs, which is the existing rule.
- Running the new pipeline on the user's GPU without their go-ahead.

## Expected effect

Re-locating the quotes of the stored `@2` runs offline (no model calls) with the new rule moves exactly one span: `CI` on posting A, from "Specific" to "CI". On the current labels and judgments, recall goes from 88% (90/102) to 89% (91/102), and extraction misses go from 12 to 11. Precision (65%, 187/286) is unchanged. New `@3` runs should reproduce this if the model output is the same. Temperature 0 and a fixed seed make that likely, but Ollama doesn't guarantee it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `posting-enrichment`: "Validation against the text" says where a verified quote is placed: at its first whole-word occurrence, preferring the source line.

## Impact

- **Code.** `src/jobhunt/enrich/validate.py` (`locate`, a shared whole-word helper, `VERSION`). `src/jobhunt/enrich/evaluate.py` (`placements` calls the shared helper). A comment in `db.py`.
- **Schema.** No migration.
- **Stored runs.** The pipeline id changes, so the eval and the posting list's "already extracted" check treat `v@2` runs as a different pipeline. Old runs stay viewable. Queued jobs under `v@2` fail with "not available in this version", which is existing behaviour.
- **Tests.** Pipeline-id strings in `tests/conftest.py` and `tests/test_enrich_pipeline.py`, plus new `locate` cases.
- **Docs.** The pipeline id in CLAUDE.md ("Model enrichment").
- **GPU.** The next `jobhunt eval` makes 9 new runs (about 30 s each). Ask the user first.
