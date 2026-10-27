## 1. Shared whole-word rule (`enrich/validate.py`, `enrich/evaluate.py`) (D1)

- [x] 1.1 Add the occurrence helper to `validate.py` (find every normalised occurrence; keep whole-word ones, else all) and rewrite `evaluate.placements` to use it. Verify that the existing placement tests in `tests/test_evaluate.py` (`test_placement_*`, `test_absent_quote_has_no_placement`) pass unchanged.

## 2. Whole-word `locate` (D2, D3, D4)

- [x] 2.1 Make `locate` take the first helper result in each search window (source line, then whole text). Bump `validate.VERSION` to 3. Verify with new tests in `tests/test_enrich_pipeline.py`, one for each spec scenario:
  - `CI` in "Specific tooling: Git, CI, containers" lands on "CI"
  - `C#` in "Strong C#/.NET skills" lands on "C#"
  - "Kubernete" against "Kubernetes" verifies through the fallback
  - with `within` set to the second line, a quote found as a whole word on both lines lands on the second line
  - a partial-word hit on the source line beats a whole-word hit elsewhere

  Also verify that the existing `locate` tests (lines 82–91) still pass.
- [x] 2.2 Update every pipeline-id string to `validate=v@3`: `tests/conftest.py` (`PIPELINE`), `tests/test_enrich_pipeline.py`, and the comment in `src/jobhunt/db.py`. Keep `test_jobs.py`'s `seg=gone@1 … validate=v@1` case as is. Verify with `grep -rn "validate=v@2" src tests`, which should find nothing.

## 3. Docs and full test run

- [x] 3.1 Update CLAUDE.md: the pipeline id in "Model enrichment", and the `validate.py` line in "Architecture" (add whole-word quote placement, shared with the eval). Verify with `grep -n "v@2" CLAUDE.md`, which should find nothing.
- [x] 3.2 Run `pytest`, and `JOBHUNT_TEST_PG_URL=postgresql+psycopg:///jobhunt_test pytest` if Postgres is available. Verify that both pass, then run `openspec validate locate-quotes-on-whole-words`.

## 4. Measure (needs the user's go-ahead before any GPU use)

- [x] 4.1 Ask the user to approve 9 model runs (about 30 s each) on their GPU. Verify by explicit user confirmation in the conversation; do not proceed without it.
- [x] 4.2 Copy `data/jobhunt.db`, then run `jobhunt eval`. Verify that it reports 9 new runs, 0 failures, and recall of 91/102 with precision of 187/286. Those figures assume the labels and judgments as of 2026-10-04. If the user has changed them since, compare against a `v@2` re-score instead, recorded with `jobhunt eval --ollama-url http://127.0.0.1:9` before task 2.1 (0 new runs): expect exactly one more matched mark (`CI/CD`) and the same precision. If the figures differ, diff the `@3` and `@2` suggestions per posting and report which differences come from model drift and which from the validator.

  Baseline recorded during apply (judgments had changed: the 25 unjudged suggestions are now judged). Tasks 1.1 and 2.1 landed together, so `jobhunt eval` could no longer score `v@2`. The baseline was instead re-scored offline from the stored `v@2` runs (`evaluate.score` with no client): recall 90/102, precision 208/311, 0 unjudged. Running the new `locate` over the same stored quotes moves one span (`CI` on posting A) and gives recall 91/102, precision 208/311. Those are the figures to expect.
