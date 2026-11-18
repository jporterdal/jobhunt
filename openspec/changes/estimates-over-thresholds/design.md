## Context

See proposal.md, "Why". Two comparisons feed adoption decisions:

- **MCP rollouts** (`scripts/mcp_eval/compare.py`): per question, two pass counts, 10 samples against 10 by default. A one-sided Fisher exact test (hypergeometric, total passes fixed) gives `p_better` and `p_worse`, and `ALPHA = 0.05` turns them into `better` / `worse` / `within noise` (`more` / `fewer` / `within noise` for `--conditions`), plus a set verdict. The adoption rule in the `mcp-evaluation` spec is written in those verdicts.
- **Link methods** (`src/jobhunt/enrich/link_eval.py`): reference posting skills a candidate fixes and breaks against the current method, a one-sided exact sign test, and `SIGNIFICANCE = 0.05` giving `better` / `worse` / `within noise` / `same`. CLAUDE.md and `docs/measurement.md` make a method current "only on a `better` verdict, or with the user's explicit agreement and the reason recorded".

Both designs fix each side's sample count, not the number of passes or of differing skills. At 10 against 10, a question passing 7 or more under the current code can't reach p ≤ 0.05 however much a candidate improves it; dev-2's history effect (2/10 → 6/10) moves across 0.05 depending only on the test (Fisher 0.085, mid-p 0.047).

## Goals / Non-Goals

**Goals:**
- Reports that show the size of each difference, its precision and the strength of evidence, with no figure turned into a verdict by a cutoff.
- One p-value method, well calibrated at small samples, for both comparisons.
- Adoption only by the user's recorded decision, asked for with the figures in front of them.

**Non-Goals:**
- Changing what is sampled, the default sample counts, or how a sample passes.
- Combining questions or reference skills into one test, or correcting for several tests (no threshold is used, so there is no error rate to control).
- Bayesian modelling beyond the cross-check in the docs.
- The skill-extraction eval (`jobhunt eval`): it reports precision and recall without p-values or verdicts, and its adoption wording ("figures for all postings") stays.
- Editing archived designs.

## Decisions

### D1. Mid-p for both tests

The one-sided mid-p value for the observed direction: P(a result further that way than observed) + ½ P(the observed result), under the same null hypothesis as today. For MCP, the pooled passes are shared at random between the two stages (hypergeometric); for linking, each differing reference skill goes either way with probability ½ (binomial). The two directions' mid-p values add to 1, so equal counts give 0.5 (Fisher's two one-sided p-values give 1.000 each, which reads as evidence against both directions).

Why: conditioning on the total makes the exact p-value conservative by about half the probability of the observed outcome, and at these sample sizes that is large (dev-2: 0.085 exact, 0.047 mid-p). Mid-p removes most of that bias and is close to the posterior probability of the opposite direction under uniform priors (dev-2: 0.040; dev-5: mid-p 0.167, posterior 0.155). Its known drawback, a false-positive rate that can slightly exceed the nominal level, matters only when it is compared with a cutoff, which this change removes.

The report shows the mid-p for the observed direction only; the other direction's is 1 minus it. JSON carries both (`mid_p_more`, `mid_p_fewer`) so a reader never has to work it out.

*Alternatives:* keep Fisher's p (conservative, and discrete enough to flip conclusions); Barnard's or Boschloo's unconditional exact test (fits the design, but needs scipy or a search over the nuisance parameter for a similar answer); report the posterior probability instead (needs a prior to defend; it stays a reading aid in the docs, see Open Questions).

### D2. Estimates with intervals

- **MCP:** the difference in pass rate, second minus first, with a 95% Newcombe hybrid score interval (built from the two Wilson intervals). It stays within [−1, 1] and behaves at 0/n and n/n, where the Wald interval collapses. When both stages passed, or both failed, every sample of a question, the report says so instead of giving an interval: the data say nothing about a difference there.
- **Linking:** the net change in reference skills right, (fixed − broken) / reference size, with a 95% interval for paired proportions (Newcombe's method 10, which uses the same Wilson intervals and the phi correlation of the paired table). The comparison is paired (same reference skills under both methods), so an unpaired interval would be too wide.

Both use only the standard library (`math`), like the existing tests.

*Alternative:* report only counts and mid-p. Rejected: the stance is that estimates come first, and the interval is what shows how little 10 samples can tell.

### D3. Direction words, no verdicts

Each row names the observed direction, which describes the counts and nothing more: `more`, `fewer` or `same` for MCP (both comparisons, so the two now read alike), `more right`, `fewer right` or `same` for linking. The set verdict goes; the set line counts questions in each direction. `ALPHA`, `SIGNIFICANCE`, `better`, `worse` and `within noise` are removed from the code, reports and docs (archived designs keep them).

### D4. What the reports show

- **`compare.py` text:** per question, `a/n -> b/m`, direction, difference with interval, mid-p; then the direction counts. Held-out questions stay counts plus figures computed from them, as today; no held-out transcript is read.
- **`compare.py --json`:** per question `first`/`second` (or `current`/`candidate`) counts, `direction`, `difference`, `interval` (`[low, high]`, or `null` when every sample passed or failed in both, with `all_same: "passed"`/`"failed"`), `mid_p_more`, `mid_p_fewer`; per set `directions` (counts). `verdict`, `p_better`, `p_worse`, `p_more` and `p_fewer` go.
- **`eval --links`:** the combination line gives fixed, broken, direction, net change with interval and mid-p in place of `verdict: …`; JSON per combination `comparison: {fixed, broke, direction, net, interval, mid_p}` in place of `verdict` and `p`.

Figures are rounded for display (differences to two places, mid-p to three); JSON keeps four places.

### D5. Adoption is only the user's recorded decision

A wording or result change to the MCP server, and a new linking method, are adopted only when the user decides so. The agent (or person) running the measurement runs what the spec requires, presents the figures, and asks the user for the decision; it never decides, infers or assumes adoption, whatever the figures show, and an earlier "go ahead" to measure is not a decision to adopt. The change's design records the figures, the user's decision and the user's reasons, in the user's words or as the user confirmed them. The specs list what must be presented (for MCP: both conditions' dev and held-out comparisons, any dev question that moved the other way, and the session batch; for linking: the comparison and the differing posting skills).

Why: at these sample sizes no rule over the figures is informative enough to decide alone, a rule on estimates would only move the bright line from the p-value to the effect, and the user is the one person who weighs mechanism, diagnostics and cost together. The measurements still have to be run and the figures recorded, so the decision rests on evidence and leaves a trail.

*Alternative considered:* a rule on the estimates (for example, the dev interval's lower bound above some difference). Reproducible and needs no judgement, but at 10 samples the intervals are 0.6–0.75 wide, so such a rule would rarely say anything, and it is still a threshold. The user chose the recorded decision.

### D6. Past results restated, archives kept

`docs/measurement.md`'s link table is restated from its recorded counts (79 reference skills; the current method got 48 right), replacing the verdict column:

| Method | Fixed | Broke | Net change [95% interval] | mid-p |
|---|---|---|---|---|
| Judge `@2` | 3 | 1 | +0.025 [−0.024, +0.075] | 0.188 |
| Judge `@6` | 2 | 4 | −0.025 [−0.085, +0.035] | 0.227 |
| Expanded phrasings (`skill-expand@1`) | 10 | 18 | −0.101 [−0.225, +0.028] | 0.068 |
| Shortlist trimmed to matched phrases | 2 | 9 | −0.089 [−0.166, −0.009] | 0.019 |

`docs/mcp-eval.md`'s worked example (2 against 8, 6 against 8) is restated the same way. Comments in `links.py` that cite "within noise" or a p-value are restated as counts and mid-p. Archived designs aren't edited: they record what was decided, and why, at the time.

## Risks / Trade-offs

- [A decision can drift toward what the user hopes for] → The spec requires the measurements to be run and the figures presented and recorded with the decision and its reasons; held-out stays unread; the session batch still runs.
- [Without a rule, two people could decide differently on the same figures] → Accepted: there is one user, and the recorded reasons let a later decision be checked against an earlier one.
- [An agent treats a large difference as permission] → The specs' "Large differences don't decide" scenarios and the docs say adoption needs the user's answer; CLAUDE.md repeats it.
- [Breaking JSON fields] → Only the project's own scripts and tests read them; they change together. Old stage directories need no change: `compare.py` recomputes from their stored samples.
- [Mid-p is less familiar than Fisher's p] → `docs/mcp-eval.md` and `docs/measurement.md` define it, with a worked example and the posterior cross-check.

## Migration Plan

No data changes and no migration: stages and judgments are read as they are. Rollback is reverting the code and docs; the specs' removed requirements come back with the revert.

## Open Questions

- Whether reports should also show the posterior probability under uniform priors beside the mid-p. For now it appears only in the docs as a reading aid; adding it later changes no spec requirement's intent beyond one more field.
