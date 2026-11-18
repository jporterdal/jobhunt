## Why

Both measurements that decide whether a method is adopted classify each comparison by a p-value cutoff: `scripts/mcp_eval/compare.py` (MCP rollouts, a one-sided Fisher exact test at p ≤ 0.05) and `jobhunt eval --links` (a one-sided sign test at p ≤ 0.05). A cutoff turns continuous evidence into a yes or no that samples this small can't support: in `add-mcp-eval-history`'s measurements, dev-2 (2/10 → 6/10) falls on opposite sides of 0.05 under Fisher's p (0.085) and mid-p (0.047), the same data with a different verdict. The project's stance, following the ASA's 2016 statement on p-values, is to avoid significance thresholds, especially in isolation: estimates and evidence are the gold standard. Fisher's test is also conservative for these designs, which fix each side's sample count but not the number of passes.

## What Changes

- **BREAKING (report and JSON):** comparisons give estimates and evidence, not verdicts. Each row shows the counts, the observed direction, the estimated difference with a 95% interval, and a one-sided mid-p value. `better`, `worse`, `within noise` and the set verdict are removed from `compare.py` (both comparisons) and from `jobhunt eval --links`, with their JSON fields.
- **Mid-p replaces the exact p-values:** for the MCP comparisons (Fisher's, from the hypergeometric distribution) and the link comparison (the sign test).
- **Adoption is only the user's recorded decision:** for a change to the MCP server's wording or results, and for a new linking method. The agent running the measurement presents the required figures and asks the user; it never decides or infers adoption. The design records the figures, the user's decision and the user's reasons. No single figure decides.
- **Docs:** `docs/mcp-eval.md` and `docs/measurement.md` explain the figures and how to read them, and past link results in `docs/measurement.md` are restated from their recorded counts. CLAUDE.md's adoption lines follow, as does the holdout-share help on the settings page.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `mcp-evaluation`: the comparison of code versions and the comparison of conditions report estimates, intervals and mid-p values instead of verdicts; the adoption rule becomes the user's recorded decision over stated figures.
- `link-evaluation`: comparing linking methods reports fixed, broken, the net change with an interval and a mid-p value instead of a verdict; adopting a linking method becomes the user's recorded decision.
- `enrichment-evaluation`: the holdout-share help no longer refers to comparisons coming out "within noise".

## Impact

- **Changed:** `scripts/mcp_eval/compare.py` and its `--json` fields; `src/jobhunt/enrich/link_eval.py` and the `eval --links` report and JSON; `src/jobhunt/web/templates/settings.html` (one help line); comments in `src/jobhunt/enrich/links.py` that cite verdicts; `tests/test_mcp_eval.py`, `tests/test_link_eval.py`; `docs/mcp-eval.md`, `docs/measurement.md`, CLAUDE.md.
- **Unchanged:** what is run, stored or scored. No stage, run or judgment is redone, and stored stages and judgments are compared as they stand. Archived designs keep the verdicts they recorded at the time.
- **No GPU time:** every restated figure comes from recorded counts.

## Parser impact

None: see [parser-impact.md](parser-impact.md).
