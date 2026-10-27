## Why

`jobhunt eval` stores its extraction runs in the same table, through the same writer, as the app's own runs, and the app uses each posting's newest successful run on its latest snapshot whatever made it. So measuring a method makes it the app's method on every labelled posting. It has already happened. On 2026-10-06, 9 of the 40 postings with skills (all 9 labelled postings) used `atomic@4` runs, a method that was measured and not adopted. Their suggestions became posting skills, were judged for links, and were offered for acceptance. Every count built on posting skills inherits this. That includes the gaps `add-skill-match` will show, so it has to be fixed first.

The side-by-side machinery that let it happen (several `atomic` versions registered, a Settings choice between them, queued jobs running whichever version they name) pays off when the person using the app can't change the code. Here the user is also the developer, and rolling back is a one-line change. `improve-skill-linking` reached the same conclusion for links: the app uses one linking method, named by the code, and measuring stores its results where the app never reads them.

## What Changes

- **Each run records what made it.** A run is either an app run (made by the job queue) or an eval run (made by `jobhunt eval`). Existing runs are classified by the job that stored them: the 33 runs a posting job points at are app runs, and the other 45 are eval runs.
- **The app uses app runs only.** That covers a posting's skills (and so links and their re-judging), the salary in the posting list, the "Model says" panel and its list of runs, accepting suggestions, and the count bulk extraction offers. Eval runs are read only by `jobhunt eval`. The eval still reuses any stored run, app or eval, with the same snapshot, model and pipeline, and stores new ones as eval runs. An eval run never becomes an app run.
- **The 9 labelled postings lose their model suggestions until they are extracted again.** None of them has an app run. Their skill marks (the user labelled every skill, and accepted suggestions are marks) remain their posting skills. Rejections stay. Bulk extraction now counts them as unextracted, so the user can re-extract them whenever they choose. Nothing is re-extracted automatically.
- **One skill extraction method in the app.** The code names it (`atomic@2`). **BREAKING:** the Settings page no longer offers a skill extraction method, and the `llm.skills` setting is gone (it was never stored in the user's database).
- **`atomic@4` is deleted.** That removes its prompt, its registration and its requirement. Its stored runs stay, as eval runs. Skill extractors stay registered by `name@version`, so one candidate version can sit beside the app's method while it is measured with `jobhunt eval --skills`. A candidate is never reachable from the app, and a measured candidate that isn't adopted is deleted. Comparing methods side by side needs a candidate to be registered.
- **A queued extraction naming a version the code no longer has fails with an error,** as it already does today.
- **Unchanged.** The model and segmentation-method settings, the "marks selected after a run" warning (which still counts any run, since eval runs were shown in the app before this change), and how the eval scores.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `posting-enrichment`: "Step-wise extraction with replaceable steps" (one skill method in the app, a candidate for measuring only), "Stricter skill extraction" (removed), "Derived data is stored separately and never edited" (a run records whether the app or the eval made it), "Requesting extraction", "Model output on the posting page", "Accepting and rejecting suggestions" and "Salary in the posting list" (app runs only).
- `skill-linking`: "Skills a posting has" uses the latest successful app run.
- `llm-connection`: "Model settings" drops the skill extraction method.
- `enrichment-evaluation`: "Evaluation command" stores its runs as eval runs that the app never uses, and checks methods against the app's method and its candidates. "Comparing skill extraction methods" compares the app's method with a registered candidate.

## Impact

- **Order.** Comes before `add-skill-match`. It also modifies `enrichment-evaluation`, as FUTURE_CHANGE.md item 1 (same-line matching) would, so propose that one after this one is archived.
- **Schema.** A migration (`0007`) adds the run's origin to `posting_enrichments` and fills it from `llm_jobs.enrichment_id`. Downgrading drops the column, and the leak returns.
- **Code.**
  - `enrich/derived.py`: `save_run` takes the origin.
  - `enrich/jobs.py`: stores app runs; `current_skills` becomes the code's constant.
  - `enrich/evaluate.py`: stores eval runs, keeps reusing any run, checks `--skills` against the app's method and its candidates.
  - `enrich/pipeline.py` and `enrich/skills.py`: `CURRENT_SKILLS`, and `atomic@4` deleted.
  - `queries.py`: app runs only in `_latest_successful_runs`, `enrichment_panel` and `unextracted_ids`.
  - `userdata.py`: no `llm.skills` setting; only app runs are acceptable.
  - `web/llm.py` and `templates/settings.html`: the skill-method choice removed.
- **Tests.** Settings, jobs and eval tests that use `atomic@4` are rewritten against a test-only candidate. New tests cover isolation (an eval run never reaches posting skills, the panel, the salary column, acceptance or the bulk count) and the migration's backfill.
- **Docs.** CLAUDE.md ("Model enrichment", the data kinds, "Data and backups" for the downgrade), and FUTURE_CHANGE.md (item 2 removed; item 3's figures recounted).
- **Data after upgrading.** The 9 labelled postings show only their marks until re-extracted (9 runs of GPU work, started by the user). Their stored link judgments stay. Posting skills that no longer appear anywhere just stop being listed.
