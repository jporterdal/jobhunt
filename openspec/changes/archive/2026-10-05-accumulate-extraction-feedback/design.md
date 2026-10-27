## Context

See proposal.md for motivation. Current state after `tighten-skill-definition`:
- `pipeline.skill_extractors()` is keyed by `name@version` (`atomic@2`, `atomic@4`), and `DEFAULT_SKILLS = "atomic@2"`. `steps_for(segmenter)` always uses the default; `steps_from_id` resolves either id.
- `jobs.current_pipeline` builds the pipeline id from the `llm.model` and `llm.segmenter` settings. `evaluate.evaluate(engine, client, model, segmenter, fresh)` returns one `Report` for one pipeline. `Counts` and `score` aggregate over all labelled postings at once. `report_json` holds counts only.
- `rejected_suggestions` is `(job_id, skill_key, created_at)`. `userdata.reject_suggestion` and its undo are the only writers. `_panel.html` has one reject action per suggestion and a "show rejected" control.
- `posting_triage.skills_complete_at` is set when the flag is set and cleared when it is cleared, so it holds the latest flagging only.
- Marks have `created_at`. Runs have `finished_at` and `status`.

## Goals / Non-Goals

**Goals:**
- Every judgment the user makes from now on is kept in a form a later prompt, filter or model change can be measured against.
- Comparing two skill methods is one command with no ad-hoc scripts.

**Non-Goals:**
- Keeping a held-out set honest automatically. The user decides when to start one; the code only reports it.
- Statistical tests on the differences. With tens of postings, the per-mark difference list is more useful than a p-value.

## Decisions

### D1. The skill method is a setting holding `name@version`

`llm.skills` joins `DEFAULT_SETTINGS` with the value `"atomic@2"`, and `set_setting` validates it against `skill_extractors()`. `steps_for(segmenter, skills)` takes both; `jobs.current_pipeline` and `evaluate` pass the setting. When `get_setting` returns a method the code no longer has, the caller uses `DEFAULT_SKILLS`, and the settings page shows the stored value as unavailable. The key matches the registry, so no mapping table is needed. The settings page lists methods in registry order.

*Alternative:* store only the name and always take the latest version. Not taken: two versions of one name are exactly what needs choosing.

### D2. `--skills` takes a comma-separated list; one report per method, one renderer for several

`evaluate()` gains `skills: str | None` and keeps returning one `Report`. The CLI splits `--skills` and validates every method first. It then plans the needed runs for every method (`reusable_run` per posting and method) and prints the count per method before any model call. If Ollama is unreachable and any method needs runs, it exits without running any. For a single method the output is as today, plus the new lines (D4–D6). For several methods, a comparison renderer prints a table with one column per method, followed by the mark differences.

Mark differences come from each report's per-posting matched-mark indices (`match` already returns the pairs): a selected mark is listed when some methods match it and others don't, with the methods that match it.

*Alternative:* a separate `jobhunt compare` command. Not taken: it would duplicate the eval's options and run planning.

### D3. Scores are computed per posting, then summed over sets

`score` fills a per-posting `Counts`. `Counts` gets `__add__`, and the report sums postings into "development", "held-out" and "all". This also gives the JSON per-posting detail (D6) without a second pass. Aggregates over every posting must stay identical to today's: the existing eval tests keep passing unchanged, and re-scoring the stored `atomic@2` runs without a model still gives 91/102 and 103 wrong.

### D4. Held-out membership uses the first time a posting was flagged complete

Migration `0004` adds `posting_triage.skills_first_complete_at` (nullable), filled from `skills_complete_at` where that is set. `userdata.set_skills_complete` sets it when it is empty and the flag is being set, and never clears it. `eval.holdout_start` in `app_settings` holds the start (UTC ISO time, or empty). The settings page shows it with set and clear actions, and the number of labelled postings in each set.

A posting is held-out when `skills_first_complete_at > holdout_start`. Postings flagged, cleared and not flagged again before the migration lose their first time; they get it when flagged next. That edge doesn't occur in the current data (every labelled posting is flagged now).

*Alternative:* `skills_complete_at`, with no migration. Not taken: re-flagging a development posting after editing its marks would move it into the held-out set, although prompts were already tuned on it.

### D5. Rejection reasons: a nullable column, two actions

Migration `0004` adds `rejected_suggestions.reason`: `'not-a-skill'`, `'not-for-me'` or NULL for rejections made before this change. `userdata.reject_suggestion` takes a required reason for new rejections. `userdata.set_rejection_reason` changes it on an existing row and refuses unknown values. The panel replaces the single reject action with two ("Not a skill", "Not for me"), so rejecting still takes one click. The shown-rejected list shows the reason, or "no reason" for NULL, with the two actions to set it.

The eval reads the reason with the rejected keys (`rejected_keys` returns a key → reason map) and counts wrong suggestions per reason. Precision is unchanged: every rejection is wrong.

*Alternative:* free-text reasons. Not taken: two fixed values can be counted and later drive a blocklist; free text can't without reading it.

### D6. Marks selected after a run, and JSON detail

For each labelled posting, the earliest `finished_at` of a succeeded run on that posting (any snapshot, model or pipeline) is compared with each selected mark's `created_at`. Later marks are counted per set. The rule is a heuristic: the user may not have looked at the suggestions, and runs made by `jobhunt eval` itself count too. It is reported as a warning and never changes scoring.

`report_json` adds `postings`: for each posting, its job id, title, set, and per method the missed selected marks (name, importance, quote, attributed step), the wrong suggestions (name, quote, reason) and the unjudged suggestions (name, importance, quote). Existing top-level fields keep their meaning for a single method. For several methods, the top level becomes `{"methods": [<single-method report>...], "differences": [...]}`.

## Risks / Trade-offs

- [The held-out set grows slowly (a few postings a week), and figures on 3–4 postings are noisy] → The report shows each set's posting count. The mark differences list says which marks moved, which matters more than percentages at this size.
- [Rejecting gets one more decision] → Two buttons in place of one keep it one click. Earlier rejections without a reason stay valid.
- [The "selected after a run" count flags innocent marks] → It's a warning, worded as possible, and never changes scores.
- [Several methods mean several GPU batches] → The command states the new runs per method before making any. Claude asks the user before running it on the GPU.
- [JSON shape changes for several methods] → The single-method shape stays a superset of today's; only the new multi-method form differs.

## Migration Plan

Migration `0004_feedback` adds `posting_triage.skills_first_complete_at` (filled from `skills_complete_at`) and `rejected_suggestions.reason` (NULL). `downgrade()` drops both. Back up `data/jobhunt.db` before the first `serve` or `import` after upgrading, as for any migration. `tests/test_migrate.py` checks the migrated schema against `db.metadata` on SQLite and Postgres.

## Open Questions

- When to start the held-out set. Suggested: right after this change is applied, so the 9 current postings form the development set. It is the user's call, made on the settings page, and doesn't change the code.
