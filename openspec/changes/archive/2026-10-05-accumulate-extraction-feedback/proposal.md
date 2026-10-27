## Why

`tighten-skill-definition` measured two stricter skill prompts on the 9 labelled postings. Neither became the default: each cut wrong suggestions by about three quarters, but lost 14–15 of the user's 102 selected marks. The user wants to revisit this once they have labelled more postings and judged more suggestions. Four things stand in the way:
- **The stricter prompt can't be chosen.** `atomic@4` is registered beside the default `atomic@2`, but neither settings nor `jobhunt eval` can select it.
- **Methods can't be compared directly.** Comparing two prompts took hand-written scripts that reached into the eval's internals: one to score a stored run of a method other than the current one, and one to list which marks each method found. The JSON report holds only counts.
- **The labelled set is no longer a fair test.** Both stricter prompts were revised against these 9 postings, so scores on them flatter those prompts. Nothing separates them from postings labelled later.
- **A rejection doesn't say why.** Of `atomic@4`'s 28 wrong suggestions, 11 were real skills the user doesn't want (Cursor, Ray, Lambda); the rest were not skills at all. These need different fixes, a prompt change or a personal blocklist, but the eval counts them as one number. A reason can't be added later from memory, so collecting it should start now.

## What Changes

- **Choose the skill extraction method.** The settings page offers the registered skill extraction methods (`atomic@2`, `atomic@4`), defaulting to `atomic@2`. Extraction requested from the posting page or list uses the chosen one.
- **Compare methods in one eval.** `jobhunt eval --skills atomic@2,atomic@4` evaluates each method on the same labelled postings and prints their figures side by side, followed by the selected marks found by some methods but not others and the wrong suggestions of each. Runs are reused per method as before, so comparing methods that already have stored runs needs no model calls. Without `--skills`, the setting is used.
- **Development and held-out postings.** The user can start a held-out set: from then on, postings first flagged as labelled later are reported apart from the earlier ones (the development set). Re-flagging a development posting keeps it there. Figures are shown for each set and for both together. Until the user starts one, the report is as today.
- **Why a suggestion was rejected.** Rejecting a suggestion takes a reason: **not a skill** or **not for me**. Earlier rejections have no reason; the user can set one on any rejected suggestion. The eval breaks wrong suggestions down by reason, without changing how precision is computed.
- **Marks selected after a run.** The report counts selected marks created after the posting already had a successful run. Such marks may have been prompted by a suggestion, which flatters recall. The count is a warning; scoring is unchanged.
- **More detail in JSON.** The JSON report lists missed marks and wrong and unjudged suggestions by name for each posting, not only counts.

Out of scope:
- **Hiding a skill on every posting (global rejection).** The "not for me" reason is what such a change would build on.
- **Changing either prompt, or the default method.** Deciding again is the user's call once the held-out set has grown.
- **Few-shot examples, filters or fine-tuning built from the judgments.** This change only keeps the data needed for them.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `llm-connection`: "Model settings" adds the skill extraction method.
- `posting-enrichment`: "Requesting extraction" uses the chosen skill extraction method. "Accepting and rejecting suggestions" adds the rejection reason and setting a reason on an earlier rejection.
- `enrichment-evaluation`: "Evaluation command" adds choosing one or more skill extraction methods, the side-by-side comparison, the development and held-out sets, the breakdown of wrong suggestions by reason, the count of marks selected after a run, and per-posting detail in JSON.

## Impact

- **Order.** Apply and archive `tighten-skill-definition` first: it registers `atomic@2` and `atomic@4` side by side.
- **Code.** `db.py` (the two columns), `userdata.py` (the `llm.skills` setting, the held-out start, rejection reasons, the first-complete time), `enrich/jobs.py` (the pipeline id from the setting), `enrich/evaluate.py` and `cli.py` (several methods, sets, reasons, warning count, JSON detail), `web/llm.py` and templates (the settings choice, the two reject actions, setting a reason on a rejected suggestion).
- **Schema.** One migration (`0004`): a nullable reason column on `rejected_suggestions` (existing rejections keep no reason), and the time a posting's labelling was first flagged complete on `posting_triage`, filled from the current flag's time for postings flagged now. The held-out start is stored in `app_settings`, which needs no migration.
- **Data kinds.** Reasons and the held-out start are user-authored and written only by `userdata.py`.
- **Tests.** The settings validation and page, the reject actions and reason updates, the migration (`tests/test_migrate.py`), and eval tests for several methods, both sets, the reason breakdown, the warning count and the JSON detail. All run without Ollama.
- **Docs.** CLAUDE.md: settings, the `eval` options and the labelling advice.
- **GPU.** None needed to build or test. Measuring a method on postings without a stored run uses the GPU, as `jobhunt eval` does today; Claude asks the user first.
