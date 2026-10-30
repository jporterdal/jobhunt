## 0. Before starting

- [x] 0.1 Archive `allocate-eval-sets-randomly` first (this change's spec builds on its "Dev and holdout sets"), and verify `openspec list` no longer shows it and `openspec/specs/enrichment-evaluation/spec.md` has "Dev and holdout sets"

## 1. Ages and the window

- [x] 1.1 Add `Age` and `parse_age` to `enrich/evaluate.py` (D1): days and weeks by `timedelta`, months and years by calendar month with the day clamped; verify with tests for `7d`, `2w`, `12m`, `1y`, 31 March − `1m` (leap and non-leap year), `str(Age)`, and refusals of `0d`, `12months`, `-1m`, `1.5y`, `m`
- [x] 1.2 Add `posted_on` (latest snapshot's `posted_on_estimate`, else `first_seen_at`'s UTC date) and `labelled_at` (`skills_complete_at`) to `Labelled` and `labelled_set`; verify with a test that a posting without a posted date takes its first-seen day, and one flagged, cleared and flagged again has the latest time
- [x] 1.3 Add `Window` (D2) with `posted_since`, `labelled_since` and `contains`; verify with tests for each option alone, both together (a posting must pass both), and the boundary day and moment (kept)

## 2. The report

- [x] 2.1 Move the set grouping into `_groups(postings, show_drawn)` and add `Report.window` and `Report.windowed_sets()` (D3); `execute` takes `window=None`; verify that `sets()` is unchanged on the existing tests and that a holdout posting outside the window stays in the full holdout figures only
- [x] 2.2 Windowed text report (D4): window header with since-dates and inside/left-out counts, the note, a two-column `all`/`in window` table per set; verify with tests that the text without a window is byte-for-byte what it was, and that an empty window shows `0 of N` with `n/a` ratios
- [x] 2.3 Windowed JSON (D5): `window`, `windowed` and `per_posting[].in_window`, only with a window; verify with a test that JSON without a window equals today's, and that with one the top-level figures and `sets` are unchanged
- [x] 2.4 Windowed comparison (D4, D5): a second per-set table with method columns, `(outside window)` in the mark differences, `in_window` on `differences` entries; verify with a two-method test (stored runs, `FakeLLM`, no Ollama)

## 3. The CLI

- [x] 3.1 Add `--posted-within` and `--labelled-within` to `jobhunt eval` (argparse `type=` from `parse_age`), build one `Window` from `datetime.now(UTC)` in `_eval` and pass it to every method's `execute`; verify in `tests/test_cli_eval.py` that a windowed run reports both figures and a malformed age exits non-zero before any model request
- [x] 3.2 Refuse the window options with `--links` (D6); verify with a CLI test that it exits 1, says they don't apply to `--links`, and makes no request

## 4. Docs and checks

- [x] 4.1 Update CLAUDE.md (the "Labelling and eval" paragraph and the `jobhunt eval` lines under Commands) and `docs/measurement.md` (windows, and that decisions use the figures for all postings); verify `jobhunt eval --help` matches the options documented
- [x] 4.2 Run `pytest`, `JOBHUNT_TEST_PG_URL=… pytest` on Postgres, `ruff check` and `openspec validate add-eval-windows --strict`, and verify all pass
