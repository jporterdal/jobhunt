## Context

`validate.locate(text, quote, within)` normalises the haystack (case-fold, collapse whitespace, ASCII dashes and quotes), uses `str.find`, and maps the hit back to raw offsets. It searches `within` (the item's source line, when the model gave a valid line number) first, then the whole text. `evaluate.placements(text, quote)` uses the same normalisation but collects every occurrence. It keeps only whole-word ones, or all of them when none is whole-word. Its edge test checks a neighbouring character only when the quote's own edge character is alphanumeric.

`locate` is used by `check_skills` (with `within`) and `check_salaries` (without). Nothing else calls it.

## Goals / Non-Goals

**Goals:**
- One whole-word rule, used by both the validator and the eval.
- Results stay identical for quotes that are already placed correctly. In the stored `@2` runs, only one span out of 311 moves.

**Non-Goals:**
- Choosing between several whole-word occurrences on semantic grounds (for example, nearest to the segment). The first one in search order is used.
- Changing what counts as verified.

## Decisions

### D1. A shared `occurrences(haystack_norm, needle)` helper in `validate.py`

Move the find-all loop and the `whole()` edge test out of `evaluate.placements` into a `validate` helper that returns normalised start indices: whole-word hits, or all hits when there are no whole-word ones. Then:
- `evaluate.placements` maps every returned index to raw offsets (its behaviour is unchanged).
- `locate` maps the first returned index to raw offsets, for each search window in turn.

*Alternative:* keep `placements` in `evaluate.py` and have `validate.locate` import it. Rejected because `evaluate` depends on `validate`, not the other way round, and the rule is about locating text, which is `validate`'s job.

### D2. Whole-word preference is applied inside each search window, not across them

Order: source line (whole-word, else any) → whole text (whole-word, else any). A partial-word hit on the source line beats a whole-word hit elsewhere.

*Why:* the source line decides the item's importance, and the UI highlights the span next to that line's other suggestions. Jumping to another line would put a required suggestion's highlight on, say, a company-description line. The `CI` case is fixed either way, because "CI" is a whole word on its own source line.

*Alternative:* try whole-word in the source line, then whole-word in the text, then partial-word in either. Rejected, for the reason above. This also matches the handoff's "keep the current search order".

### D3. Edge test runs on the normalised window, not the raw text

The window is normalised on its own (as now), so the first and last characters of the window count as text boundaries. A quote at the very start of a source line is whole-word even when the raw text before the line ends in a letter. That can't happen in practice, because lines are newline-bounded.

### D4. `validate.VERSION = 3`

Stored spans can change, so the step's output changes. That calls for a version bump under the project rule. Salary items also go through `locate`, but salary quotes are long phrases, and no stored salary span moves.

## Risks / Trade-offs

- [New `@3` runs differ from `@2` runs for reasons other than the validator, because Ollama output can drift between runs even with a fixed seed] → Compare the eval report with the offline prediction in proposal.md (91/102 recall, 187/286 precision). If they differ, diff the two runs' suggestions before crediting or blaming the validator.
- [A short quote that occurs only inside words still verifies through the fallback, so `CI` with no standalone "CI" in the text still lands in "discipline"] → Accepted. Verification semantics are unchanged by design. Tightening them is a separate decision.
- [GPU cost: 9 new runs at about 30 s each] → Ask the user before running `jobhunt eval`.

## Migration Plan

No schema change. Old `v@2` runs remain viewable. Rollback is a revert: runs made under `v@3` stay stored and show their own pipeline id.
