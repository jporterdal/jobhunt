## Context

See proposal.md for the motivation. This change assumes `allocate-eval-sets-randomly` is implemented (it is, but not yet archived). Current state after it:

- `evaluate.labelled_set` reads every `posting_triage` row with `skills_complete_at` set, with its `eval_set` and `eval_set_origin`, and builds a `Labelled` from the latest snapshot (title, text) and the marks. It doesn't read the posted date or any flagging time.
- `posting_snapshots.posted_on_estimate` (a date, nullable) with `posted_on_precision`; `postings.first_seen_at` (UTC datetime, never null). `skills_complete_at` is the latest flagging (cleared on unflagging, set again on re-flagging); `skills_first_complete_at` is the first.
- `Report.sets()` returns `(name, size, Counts)` for dev, holdout, `holdout (drawn)` when some holdout posting wasn't drawn, and together. `format_text` prints one block per set (`_block`); `comparison_text` prints a table per set with one column per method (`_ROWS`); `to_dict` puts together's figures at the top level and the others under `sets`.
- `cli._eval` plans every method, then executes them; `--links` goes to `_eval_links`, and link-only options without `--links` are refused there.

## Goals / Non-Goals

**Goals:**
- Without a window, the text and JSON reports are byte-for-byte what they are today.
- Every method in one run uses the same cutoffs.
- Ages are tested without the clock: `now` is passed in, as elsewhere.

**Non-Goals:**
- Running fewer postings when a window is given. Every labelled posting is still run (or reused) and scored.
- Using `posted_on_precision`. The stored date is compared as it is.

## Decisions

### D1. Ages: `evaluate.Age` and `parse_age`

`parse_age("12m") -> Age(12, "m")`, matching `^([1-9][0-9]*)([dwmy])$`; anything else raises `ValueError("an age is a positive whole number followed by d, w, m or y, as in 12m")`. `Age.before(now) -> datetime`: days and weeks subtract a `timedelta`; months and years step back calendar months, clamping the day to the month's last (31 March − 1m is 28 or 29 February). `str(Age)` gives back `12m` for the report.

- *Alternative: 30-day months, 365-day years.* Simpler, but `12m` would then end five days short of a year, and the user writes ages in calendar terms.
- *Alternative: `python-dateutil`'s `relativedelta`.* Does the same in one call, but it's a new dependency for a dozen lines.

The CLI passes `parse_age` as argparse's `type=` (wrapped to raise `ArgumentTypeError`), so a malformed age exits with status 2 and argparse's usage line, before the database is opened.

### D2. The window: `evaluate.Window`

`Window(posted_within: Age | None, labelled_within: Age | None, now: datetime)`, built once in `cli._eval` from `datetime.now(UTC)` and shared by every method's report. It exposes `posted_since: date | None` (the UTC date of `posted_within.before(now)`) and `labelled_since: datetime | None`, and `contains(posting) -> bool`: posted date ≥ `posted_since` and `labelled_at` ≥ `labelled_since`, each test applied only when its age is given. `cli._eval` builds no `Window` when neither option is given, and everything downstream treats `None` as "no window".

`Labelled` gains `posted_on: date` (`posted_on_estimate` of the latest snapshot, else `first_seen_at`'s UTC date) and `labelled_at: datetime` (`skills_complete_at`). `labelled_set` already reads the triage row and the latest snapshot; it adds the two columns and the posting's `first_seen_at`.

- *Why `skills_complete_at` and not the first flagging:* agreed when the change was named. A posting relabelled recently reflects the user's current bar.
- *Why the UTC date for the posted cutoff:* posted dates have no time zone; at worst a posting on the boundary day lands one day off.

### D3. Windowing happens in the report, not the plan

`plan` and `execute` don't change what they run. `execute(engine, client, plan, window=None)` stores the window on the `Report`. `Report.sets()` keeps its signature and output. A new `Report.windowed_sets()` applies the same grouping to the postings inside the window and returns the same rows in the same order: `holdout (drawn)` appears exactly when it appears in `sets()`, so the two columns line up. Grouping moves into one helper, `_groups(postings, show_drawn)`, used by both.

- *Alternative: run only the postings inside the window.* Cheaper on a cold cache, but the side-by-side figures need every posting scored anyway, and stored runs make the rest free on later runs.

### D4. Text report

Without a window, `format_text` is unchanged. With one, the header gains:

```
window:   posted within 12m (since 2025-10-29), labelled within 6m (since 2026-04-29 14:02 UTC)
          5 of 13 labelled postings inside, 8 left out
note:     adopt or delete a method on the figures for all postings; windowed figures are for diagnosis
```

and each set prints as a two-column table, `all` and `in window`, using the `_ROWS` table `comparison_text` already uses (heading `dev: 7 labelled postings, 3 in window`). The `selected after a run` warning stays a row, as in the comparison. A window that keeps no posting gets the header line `0 of 13 …`, and its column shows `n/a` ratios and zero counts, as an empty holdout set does today.

`comparison_text` with a window prints, after each set's table, a second table for the same set, `dev, in window: 3 labelled postings`, with one column per method, then the note. The mark differences list stays over all postings and marks postings outside the window with `(outside window)`.

- *Alternative: keep `_block` and print the windowed block under the full one.* Puts the two figures for one measure a dozen lines apart, so comparing them means scrolling.

### D5. JSON

The existing fields keep their values. With a window, `to_dict` adds:

```json
"window": {"posted_within": "12m", "posted_since": "2025-10-29",
           "labelled_within": "6m", "labelled_since": "2026-04-29T14:02:00+00:00",
           "inside": 5, "left_out": 8,
           "note": "adopt or delete a method on the figures for all postings; windowed figures are for diagnosis"},
"windowed": {<_summary of together>, "sets": {"dev": …, "holdout": …}}
```

and `"in_window": true|false` on each `per_posting` entry. Absent options are `null`. Without a window, none of these keys appear, so an unchanged run gives unchanged JSON. `comparison_json` gets them per method through `to_dict`, and each `differences` entry gains `in_window` only with a window.

### D6. The CLI

`--posted-within AGE` and `--labelled-within AGE` on `jobhunt eval`, with help naming the units. `_eval` refuses either with `--links` (`error: --posted-within and --labelled-within don't apply to --links`, exit 1), before `_eval_links`, next to the existing check for link-only options. The stderr line before running each method is unchanged.

## Risks / Trade-offs

- [Windowed figures from a handful of postings swing a lot] → Every table heading gives the number of postings in the window; the note says the full figures decide.
- [A coarse posted date (`month`, `year` precision) or an estimate from a relative date can fall on the wrong side of the cutoff] → It's off by at most its precision; the window is for diagnosis.
- [A posting the site re-posts gets a new posted date in a later snapshot and moves into the window] → Intended: the latest snapshot is what's scored.
- [Relabelling a posting moves it into the labelled window even when only one mark changed] → Agreed when the change was named; `skills_first_complete_at` is still stored if a first-labelled window is ever wanted.

## Migration Plan

None: no schema change and nothing stored. Rollback is reverting the code.
