## Context

See proposal.md for the motivation. Current state:

- `posting_triage` (user-authored, written only by `userdata.py`) holds `skills_complete_at` (the current flag, cleared on unflagging) and `skills_first_complete_at` (the first flagging, never cleared). `userdata.set_skills_complete` sets both. The web route `POST /postings/<id>/labelled` takes only `complete`.
- A posting's set is computed on each read: `queries.held_out(first_complete_at, start)` compares the first flagging with the `eval.holdout_start` setting. `evaluate.labelled_set` and `queries.labelled_sets` (the settings page counts) both call it. Set names are `development` and `held-out` (`evaluate.DEVELOPMENT`, `HELD_OUT`).
- `Report.sets()` returns one set (`all`) while no start is recorded, otherwise development, held-out and together. `Report.to_dict()` adds `holdout_start` and, with a start, `sets.development` / `sets.held_out`. `comparison_text` uses `sets()` and names each posting's set in its mark differences.
- Settings are rows of `app_settings`, typed and validated in `userdata.get_setting` / `set_setting` against `DEFAULT_SETTINGS`. The settings page's Evaluation section has Start and Clear buttons posting to `POST /settings/holdout`.
- The user's database has 9 labelled postings, all flagged on one day, and no held-out start. The demo flags no posting complete.
- The head revision is `0011`.

## Goals / Non-Goals

**Goals:**
- A posting's set is decided once, at its first flagging, and stored, so the eval, the settings page and the posting page read it rather than compute it.
- The draw is reproducible in tests: the source of randomness is passed in.
- Upgrading keeps every set that the held-out start gave.

**Non-Goals:**
- Scoring only recent postings or recent labels. That is the follow-up change `add-eval-windows`, which adds `jobhunt eval` options and leaves membership alone.
- Changing the steepness. Odds multiplying by e per posting is fixed in the spec; there is no setting for it.
- Recording each draw's probability. Nothing reads it, and the counts behind it can be recomputed from history only roughly once postings move.

## Decisions

### D1. Two columns on `posting_triage`

`eval_set` (`dev` | `holdout`, nullable) and `eval_set_origin` (`drawn` | `chosen` | `moved` | `before-random`, nullable). Both are null until the first flagging and set together. The values are validated in `userdata.py` against `EVAL_SETS` and `EVAL_SET_ORIGINS`, as other enumerations are (`MARK_ORIGINS`, `REJECTION_REASONS`); there is no database constraint.

- *Why on `posting_triage`:* the set is one value per posting, decided by a user action, beside the flag it depends on. The table already has one row per posting and one writer.
- *Alternative: a separate `eval_sets` table with a row per move.* It would keep history of moves, but the only move is holdout → dev, and `eval_set_origin = 'moved'` records that it happened.
- `skills_first_complete_at` stays, still set at the first flagging. After this change nothing reads it except the migration, but it records when labelling was first finished, and dropping a column is a separate decision. (`add-eval-windows` uses the latest flagging, `skills_complete_at`.)

### D2. The draw lives in `userdata.set_skills_complete`

`set_skills_complete(conn, job_id, complete, now=None, choice="auto", draw=random.random)`. When `complete` is true and the posting has no set:

- `choice="dev"` or `"holdout"` stores that set with origin `chosen`;
- `choice="auto"` counts N and H inside the same transaction, computes P with `holdout_probability(share, n, h)`, and stores `holdout` if `draw() < P`, else `dev`, with origin `drawn`.

When the posting already has a set, `choice` is ignored. Any other `choice` is a `UserDataError`.

`holdout_probability(share, labelled, holdout) -> float` is a pure function at module level, tested directly against the spec's numbers (0.5, 0.989, 0.538). `draw` is a parameter so tests pass a fixed value, as `now` is passed today.

- *N and H count postings currently flagged complete* that have a set: the postings the eval scores. *Alternative: every posting that has a set, flagged or not.* It would stop unflagging a posting from moving later draws, but the aim is balance among the postings measured, and unflagging is rare.
- *Why `random.random` and not a seeded generator:* each draw is stored, so there is nothing to replay. A seed would make the next allocation predictable from the database.

### D3. Moving to dev: `userdata.move_eval_set(conn, job_id, to)`

`to="dev"` on a holdout posting sets `eval_set='dev'`, `eval_set_origin='moved'`. `to="dev"` on a dev posting does nothing. `to="holdout"` raises `UserDataError("a dev posting can't move to holdout: prompts may have been tuned on it")`. A posting with no set raises `UserDataError`. The route is `POST /postings/<id>/eval-set` with `set`, redirecting to the marks panel like `set_labelled`.

### D4. The holdout share: setting `eval.holdout_share`

`DEFAULT_SETTINGS["eval.holdout_share"] = 0.5`; `get_setting` returns a float; `set_setting` accepts a number or numeric string from 0.1 to 0.9 inclusive and refuses others ("the holdout share must be from 0.1 to 0.9"). `eval.holdout_start` leaves `DEFAULT_SETTINGS`, with `_holdout_start`.

The settings page's Evaluation section becomes one small form posting to `POST /settings/eval` (a number input, step 0.05), the counts (`queries.eval_set_counts`: dev, holdout, and how many holdout postings weren't drawn), and the help text from the spec as a short list. `POST /settings/holdout` is removed, so an old form gets 404.

- *Why a separate form and route:* the Model form saves several settings at once and requires a model; the share has nothing to do with the model and should save while Ollama is offline.

### D5. Reading sets in the eval

`Labelled` gains `set_origin`; `labelled_set` reads `eval_set` and `eval_set_origin` from `posting_triage` instead of computing them. Every labelled posting has a set after the migration, since the flag can't be set without one. `DEV, HOLDOUT = "dev", "holdout"` replace `DEVELOPMENT`, `HELD_OUT`.

`Report.sets()` always returns `dev`, `holdout`, then `holdout (drawn)` only when some holdout posting's origin isn't `drawn`, then `together`. The single-set (`all`) form goes. `Report` loses `holdout_start`, and `Plan` and `execute` stop reading the setting.

JSON: `sets` is always present, with keys `dev`, `holdout` and, when shown, `holdout_drawn`; the top-level figures stay the together figures, as now. `holdout_start` is removed. Each `per_posting` entry has `set` (`dev` | `holdout`) and `set_origin`. `comparison_text` needs no change beyond the names, since it already iterates `sets()`.

- *Alternative: keep one set while holdout is empty.* Not taken: right after upgrading, the user's report would look unchanged and give no sign that holdout exists and is empty.

### D6. The posting page

In `_marks.html`, before the first flagging, the flag form gets a `select name="choice"` (Auto, Dev, Holdout; Auto selected) beside "Labelling complete". After it, the line reads "Labelling complete since … · holdout set" (or "dev set"), with the origin as a title, and, for holdout, a small "move to dev" form. When the flag is cleared but the posting has a set, the set still shows beside the "Labelling complete" button, with no choice. The detail query already selects the whole `posting_triage` row, so the template reads `d.triage.eval_set`.

### D7. Migration `0012`

Upgrade adds both columns, then, in Python for portability: reads the `eval.holdout_start` row from `app_settings` (absent or empty means none); for each `posting_triage` row with `skills_first_complete_at` set, writes `holdout` when a start exists and the first flagging is after it, else `dev`, with origin `before-random`; deletes the `eval.holdout_start` row. Times are compared as timezone-aware datetimes, as `queries.held_out` does now.

Downgrade drops both columns. The held-out start isn't restored, so after a downgrade every labelled posting reports in one set until the user starts a held-out set again. The upgrade's docstring says so.

## Risks / Trade-offs

- [The user can predict the next draw when holdout is far behind (0.989 right after upgrading)] → Labelling happens before the click, so knowing the likely set doesn't change marks already made. After the first few postings the sets stay within a posting or two and draws are close to the share.
- [Choosing a set by hand lets selection back in: postings picked for holdout because they look interesting] → Every choice is recorded as `chosen`, and the report shows drawn-only holdout figures beside the full ones whenever they differ.
- [Moving postings to dev shrinks holdout permanently] → Draws make up for it: a holdout shortfall raises the odds of holdout for the next postings.
- [The JSON report's set fields change] → The user is the only consumer; the REMOVED requirement's migration note and CLAUDE.md state the new names.
- [Two flaggings at once could read the same counts] → One user, one browser; the worst case is a draw made with counts one posting stale.
- [Holdout figures stay noisy for weeks] → Unchanged from today; the report shows each set's count.

## Migration Plan

1. Back up `data/` before the first `serve` or `import` after upgrading, as for any migration.
2. `init_db` applies `0012`: the user's 9 labelled postings become dev (`before-random`), and the held-out start row (absent today) is deleted.
3. The Settings page shows 9 dev, 0 holdout and the share 0.5; the next labelled postings are drawn mostly into holdout until the sets balance.

Rollback: `alembic downgrade 0011` drops the set columns; draws made since the upgrade are lost.
