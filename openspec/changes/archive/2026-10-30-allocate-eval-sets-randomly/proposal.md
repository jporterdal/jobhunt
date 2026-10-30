## Why

Today the held-out set is split by time: once the user presses "Start a held-out set now", every posting first flagged "Labelling complete" after that moment is held out, and every posting before it is development. That freezes the development set at the start, so it can grow again only by clearing the start and putting every holdout posting into it. It also groups postings by when they were labelled, so a batch of similar postings labelled in one sitting all lands in one set. The user wants both sets to grow at any time, and wants each posting's set decided at random when it is labelled, so they label without knowing which set a posting will join.

## What Changes

- **A posting's set is drawn when its labelling is first flagged complete.** The draw is random but keeps the sets near a target share: the holdout set's chance rises steeply (its odds multiply by e for each posting it falls short of the target) and falls the same way when it is ahead. Balance counts labelled postings, not marks. The set is stored with the posting and kept: clearing and setting the flag again never draws again.
- **The two sets are named dev and holdout** in the UI, the report and the JSON.
- **The holdout share is a setting** (default 0.5, from 0.1 to 0.9) on the settings page, with help text saying when to change it. Changing it moves no posting; new draws move towards it.
- **The user can choose the set by hand** when flagging: Auto (the default, a draw), Dev or Holdout. A choice by hand counts toward the balance like a draw.
- **A holdout posting can be moved to dev** at any time, from the posting page. Dev postings can never be moved to holdout, since prompts may have been tuned on them.
- **The report shows dev, holdout and both together**, with the number of postings in each, and also shows the holdout figures for drawn postings alone when some holdout postings weren't drawn.
- **BREAKING:** the held-out start (`eval.holdout_start`), its settings controls and its `POST /settings/holdout` action are removed. The JSON report's set names change (`development` → `dev`, `held_out` → `holdout`), its `holdout_start` field is removed, and each posting gains how its set was chosen.
- **Postings already labelled keep their set** when the database is upgraded: postings flagged before a recorded held-out start (or every labelled posting, when none is recorded) become dev, postings flagged after it become holdout, and both are marked as allocated before random allocation.

Not in this change:
- **Eval windows** are the follow-up change **`add-eval-windows`**: optional `jobhunt eval` options that score only postings posted within a given age and postings labelled within a given age (using the latest labelling time), so overall and recent figures can be compared. They don't change which set a posting is in.
- Balancing by marks instead of postings.
- Hiding holdout postings' per-posting detail from the report.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `enrichment-evaluation`: "Development and held-out postings" is replaced by dev and holdout sets drawn at labelling, the balancing rule, choosing or moving a posting's set by hand, the holdout share setting, and the report's sets.
- `posting-triage`: "Skill labelling complete" offers the set choice when a posting is first flagged, and the posting page shows its set, with a way to move a holdout posting to dev.

## Parser impact

**None.** This changes labelling and the eval only; see [parser-impact.md](parser-impact.md).

## Impact

- `src/jobhunt/db.py` and a new Alembic revision `0012`: the posting's set and how it was chosen on `posting_triage`, filled for postings already labelled; the `eval.holdout_start` row removed.
- `src/jobhunt/userdata.py`: the draw at the first flagging, the set chosen by hand, moving to dev, the `eval.holdout_share` setting in place of `eval.holdout_start`.
- `src/jobhunt/queries.py`: set counts for the settings page in place of `held_out`/`labelled_sets`.
- `src/jobhunt/enrich/evaluate.py` and `src/jobhunt/cli.py`: sets read from the posting, the new set names, drawn-only holdout figures, JSON fields.
- `src/jobhunt/web/triage.py`, `web/llm.py`, `templates/triage/_marks.html`, `templates/settings.html`: the choice beside "Labelling complete", the set and "move to dev" on the posting page, the share setting with its help text.
- Tests: `test_suggestions.py`, `test_evaluate.py`, `test_web_llm.py`, `test_migrate.py` and new cases for the draw.
- Docs: CLAUDE.md (Labelling and eval, Settings page, Architecture), `docs/measurement.md`, README.
- No new dependency. No model is used.
