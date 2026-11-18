## 1. MCP comparison (`scripts/mcp_eval/compare.py`)

- [x] 1.1 Add mid-p for both directions (hypergeometric, ½ the observed term) beside the existing exact sums, and the Newcombe hybrid score interval for the difference in pass rate (stdlib only); verify with tests for 2/10 → 9/10 (+0.70 [+0.27, +0.87], mid-p 0.001), 6/10 → 8/10 (+0.20 [−0.19, +0.52], mid-p 0.192), 2/10 → 6/10 (mid-p 0.047), equal counts (mid-p 0.5) and the two directions adding to 1
- [x] 1.2 Replace verdicts with direction words (`more`, `fewer`, `same`) in the comparison of code versions and of conditions, report "passed every sample" / "failed every sample" in place of an interval, and replace the set verdict with direction counts; remove `ALPHA`, `verdict`, `set_verdict`, `CONDITION_WORDS` and the `better`/`worse`/`within noise` words; verify with the spec's scenarios as tests, including the set of 2 `more`, 1 `fewer`, 2 `same`
- [x] 1.3 Change the text report and `--json` fields as design D4 describes (`direction`, `difference`, `interval`, `all_same`, `mid_p_more`, `mid_p_fewer`, `directions`), keeping held-out questions as counts and figures; update the module docstring; verify with report and JSON tests and by running `compare.py` and `compare.py --conditions` on the stored `baseline-dev` and `none-dev` stages (no model run) and checking dev-2 shows +0.40 [−0.02, +0.67], mid-p 0.047
- [x] 1.4 Update `tests/test_mcp_eval.py`'s verdict tests (the `p_more` table stays; verdict assertions become direction, estimate and mid-p assertions); verify `pytest tests/test_mcp_eval.py` passes

## 2. Link comparison (`src/jobhunt/enrich/link_eval.py`)

- [x] 2.1 Give `Comparison` the reference size and the current method's right count, and add the sign-test mid-p, the direction (`more right`, `fewer right`, `same`) and the net change with Newcombe's method 10 paired interval; remove `SIGNIFICANCE` and the verdict; verify with tests for the spec's scenarios (40 skills, 20 right: 5 fixed 0 broken → +0.125 [+0.023, +0.220], mid-p 0.016; 0 fixed 4 broken → −0.100 [−0.187, −0.008], mid-p 0.031; none differing → `same`, 0.5)
- [x] 2.2 Change the text report's combination line and the JSON (`comparison: {fixed, broke, direction, net, interval, mid_p}` in place of `verdict` and `p`); verify with `tests/test_link_eval.py`'s report and JSON tests, updated
- [x] 2.3 Restate the comments in `src/jobhunt/enrich/links.py` that cite "within noise" or a p-value as counts, net change and mid-p (the figures in design D6); verify by grepping `links.py` for "within noise" and "p=" with no hits

## 3. Settings help

- [x] 3.1 Change the holdout-share help line in `src/jobhunt/web/templates/settings.html` to the spec's wording ("differences too imprecise to tell methods apart"); verify with the settings page test that checks the help text (add the assertion if none checks this line)

## 4. Documentation

- [x] 4.1 `docs/mcp-eval.md`: rewrite "The verdict, and adopting a change" and "Comparing conditions" as the figures (counts, direction, difference with interval, mid-p), how to read them without a threshold (what mid-p is and isn't, the posterior cross-check, why intervals at 10 samples are wide), and adoption as the user's recorded decision over the listed figures; restate the worked example and the opening and closing lines that say "measures better" and "within noise"; verify by grepping the file for `better`, `worse`, `within noise` and `0.05` with no stale hits
- [x] 4.2 `docs/measurement.md`: replace the paired-verdict paragraph and the link results table with design D6's figures, restate "Rules that came out of this" (adoption is the user's recorded decision) and "Known limits"; verify the same grep on that file
- [x] 4.3 CLAUDE.md: the `compare.py` and `link_eval.py` lines in the architecture, the "Known weak spots" adoption sentence, the MCP "Measuring wording and results" paragraph and the `compare.py --conditions` command comment; verify the same grep on CLAUDE.md

## 5. Checks

- [x] 5.1 Run `pytest` (SQLite, and Postgres with `JOBHUNT_TEST_PG_URL`), `ruff check` and `openspec validate --all --strict`; verify all pass
