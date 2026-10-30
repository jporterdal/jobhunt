## Why

`jobhunt eval` scores every labelled posting together, so a change in how postings are worded, or in how the user labels, is hidden by older postings. The user wants to see whether recent postings, and recently labelled ones, score differently from the whole set, without changing which set (dev or holdout) any posting is in. This is the follow-up named in `allocate-eval-sets-randomly`.

## What Changes

- **Two optional `jobhunt eval` options:** `--posted-within AGE` keeps postings whose posted date is no older than AGE, and `--labelled-within AGE` keeps postings whose labelling was last flagged complete no longer ago than AGE. AGE is a whole number and a unit counted back from now: `d` (days), `w` (weeks), `m` (months) or `y` (years), as in `--posted-within 12m --labelled-within 6m`. Given both, a posting must pass both.
- **A posting's age** is its latest snapshot's posted date, or the day it was first seen when the posting gives no date. **Labelling age** is the latest time its labelling was flagged complete, not the first.
- **One run shows both figures.** With a window, the report shows each set's figures (dev, holdout, drawn holdout when shown, together) for all labelled postings and for the postings inside the window, side by side, with how many postings the window left out. Every labelled posting is still run and scored, so the figures for all postings are the same as without a window.
- **The report says which figures decide.** With a window, it states that adopting or deleting a method uses the figures for all postings, and the windowed figures are for diagnosis.
- **The JSON report** gains the window (the options and the dates they mean), the windowed figures, and whether each posting is inside the window. Its existing fields keep their meaning and values.
- **Comparing methods** shows the windowed figures for each method too.
- **Windows never change a posting's set**, and nothing about them is stored.
- `--links` takes no window: given with `--links`, the window options are refused.

Not in this change:
- A window on the settings page or in the web UI.
- Windows for link measurement.
- Fixed dates (`--posted-since 2026-01-01`) in place of ages.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `enrichment-evaluation`: a new requirement, "Eval windows", for the two options, the side-by-side figures, the decision note and the JSON fields. It builds on "Dev and holdout sets" from `allocate-eval-sets-randomly`, which must be archived first.

## Parser impact

**None.** This changes the eval report only; see [parser-impact.md](parser-impact.md).

## Impact

- `src/jobhunt/enrich/evaluate.py`: parsing an age, each labelled posting's posted date and latest flagging, the window test, the report's windowed figures in text and JSON, and in the method comparison.
- `src/jobhunt/cli.py`: the two options, refused with `--links` and when malformed.
- Tests: `tests/test_evaluate.py`, `tests/test_cli_eval.py`.
- Docs: CLAUDE.md (Labelling and eval, Commands), `docs/measurement.md`.
- No schema change, no new dependency, no model request beyond what the eval already makes.
