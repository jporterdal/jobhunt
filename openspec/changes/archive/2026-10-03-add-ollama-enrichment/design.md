## Context

See proposal.md for the motivation. The current state that shapes the approach:

- **Three data kinds, one writer each.** `store.py` writes scraped tables and `userdata.py` writes user-authored tables. The `add-local-web-ui` design reserved `posting_enrichments(id, job_id, snapshot_id, model, prompt_version, created_at, output_json)` and `analyses` for derived data. Neither exists yet. The posting detail page already has a hidden `#model-says` panel styled `.src-derived`.
- **Skill marks** (`posting_skill_marks`) store a whitespace-collapsed quote and the snapshot it was marked on. `marks.js` finds quotes in the rendered description to highlight them. `skills.level` (`have`, `missing`, `learning`) belongs to the skill.
- **`description_text` keeps line structure.** Paragraphs and bullets are separate lines. The longest real posting has 81 lines and about 1,950 tokens.
- **Web.** Flask with a threaded dev server, htmx, and `guard.py` checking Host and Origin. Route modules stay thin, and logic lives in modules tested without Flask.
- **Ollama (measured during exploration).** Version 0.32 runs in WSL at `localhost:11434` on a 16 GB AMD GPU.
  - Model load takes 20–45 s.
  - A warm 1,950-token prompt is processed in about 1–2 s.
  - Generation runs at 20–35 tok/s.
  - A 14B Q4 model at 8k context uses about 10.7 GB of VRAM.
  - `gemma4:12b` defaults to temperature 1 and supports thinking.
  - `/api/ps` reports `size` and `size_vram` for each loaded model.
- **Extraction quality (measured).** With a single schema-constrained call per posting:
  - results changed sharply with prompt wording
  - models returned empty arrays, phi4 twice
  - required and preferred sections were dropped
  
  Every quote that was returned was verbatim.

## Goals / Non-Goals

**Goals:**

- Each step can be replaced without changing the others or old results. The fixed contract is the span: a segment is a pair of character offsets into the snapshot's text.
- Model work never blocks a request, survives restarts, and stops cleanly.
- Every model output is checked by Python against the text before it is shown as trustworthy.
- Extraction quality is measurable from the first commit.
- No new dependencies, and storage portable across Postgres and SQLite.

**Non-Goals:**

- CV parsing, ODT extraction, skill aliases, embeddings and match scores. These belong to `add-cv-skill-profile`, which will reuse the segment, extractor and validator contracts.
- Highlighting suggestions inside the description text. The panel lists quotes; only accepted marks are highlighted.
- Filtering or sorting the posting list by salary, and Insights analyses. The `analyses` table is still not created.
- Queuing extraction automatically after an import.
- More than one worker, or several Ollama servers.
- Pruning old jobs or runs.

## Decisions

### D1. A new `enrich/` package, with each part's dependencies limited

```
src/jobhunt/enrich/
    ollama.py     HTTP client for Ollama (stdlib urllib); implements the LLM protocol. No DB.
    pipeline.py   Segment / SkillItem / SalaryItem types, step protocols, step registry,
                  run_pipeline(text, llm, steps, should_stop) -> RunResult. No DB, no HTTP.
    segment.py    segmenters: "rules", "llm-lines"
    skills.py     skill extractor: "atomic"
    salary.py     pay-line locator + salary extractor: "paylines"
    validate.py   quote and amount checks, offset mapping (pure Python)
    derived.py    the only writer of posting_enrichments, enrichment_skills, enrichment_salaries
    jobs.py       llm_jobs queue (enqueue, claim, cancel, recover) and the Worker thread
    evaluate.py   labelled set, matching, metrics, report. No Flask.
web/llm.py        blueprint: status badge, settings, queue, extract actions, accept/reject
```

- `queries.py` gains the read models: the detail panel, the list salary summary, unextracted counts and the labelled filter.
- `userdata.py` gains:
  - settings
  - mark importance and origin
  - `accept_suggestion` and `accept_all`
  - rejections
  - the labelled flag

**Why a sub-package.** The model code has nine modules and is the main area the next change will extend.

**Alternative considered:** flat `llm_*.py` modules next to `store.py`. Rejected because they would crowd the top level and hide the boundaries between the pipeline steps.

### D2. A fourth data kind for the queue, and a writer for each kind

| Kind | Tables | Only writer |
|---|---|---|
| Scraped | unchanged | `store.py` |
| User-authored | existing, plus `app_settings` and `rejected_suggestions`; new columns on `posting_skill_marks` and `posting_triage` | `userdata.py` |
| Derived | `posting_enrichments`, `enrichment_skills`, `enrichment_salaries` | `enrich/derived.py` |
| Operational | `llm_jobs` | `enrich/jobs.py` |

`llm_jobs` is neither the user's data nor model output. It is a record of work, so it gets its own writer rather than blurring "derived rows are never edited", since a job's status does change. `userdata.accept_suggestion` *reads* derived rows and writes only user tables.

### D3. Schema (revision `0003_llm_enrichment`)

```
app_settings          key TEXT PK, value TEXT NOT NULL, updated_at
                      keys: llm.model, llm.num_ctx (default 8192), llm.segmenter (default llm-lines)

llm_jobs              id, job_id FK, snapshot_id FK, model, pipeline, status, error,
                      enrichment_id FK NULL, queued_at, started_at NULL, finished_at NULL
                      status: queued | running | done | failed | cancelled

posting_enrichments   id, job_id FK, snapshot_id FK (indexed), model, pipeline,
                      status (succeeded | failed), error NULL,
                      started_at, finished_at, output_json TEXT
enrichment_skills     id, enrichment_id FK (indexed), position, name, key, importance, kind,
                      quote, start_offset NULL, end_offset NULL, verified BOOL
enrichment_salaries   id, enrichment_id FK (indexed), position, min_amount FLOAT NULL,
                      max_amount FLOAT NULL, currency, period, location NULL, basis,
                      quote, start_offset NULL, end_offset NULL, verified BOOL

rejected_suggestions  job_id FK, skill_key, created_at; PK (job_id, skill_key)
posting_skill_marks   + importance TEXT NULL ('required' | 'preferred'),
                      + origin TEXT NOT NULL, server default 'selection' ('selection' | 'suggestion')
posting_triage        + skills_complete_at UTCDateTime NULL
```

**Departures from the reserved shape:**

- **`pipeline` replaces `prompt_version`.** It holds a canonical text such as `seg=llm-lines@1 skills=atomic@1 salary=paylines@1 validate=v@1`. One column identifies every step's version, and equal text means comparable runs.
- **Child tables for items.** Skills and salary ranges are stored as rows, not only inside `output_json`. The list summary, "already marked", rejections and eval then use plain portable SQL. `output_json` keeps the full step trace: segments, raw outputs, attempts and timings for each step.
- **`started_at` and `finished_at` replace `created_at`,** so eval can report run time.

**Other choices:**

- **Amounts are `Float`.** SQLAlchemy `Numeric` warns on SQLite and needs Decimal handling. Salary figures are compared and displayed, not summed to the cent.
- **Rejections are keyed by `skill_key`** (`userdata.name_key`), not by run, so they apply to later runs.
- **Failed runs are stored.** The panel and eval need their errors.

### D4. Pipeline contracts

```python
Segment(start: int, end: int, label: "required" | "preferred" | "other")
SkillItem(name, importance, kind, quote)
SalaryItem(min, max, currency, period, location, basis, quote)

class LLM(Protocol):
    def chat_json(self, system: str, user: str, schema: dict) -> dict: ...

class Segmenter(Protocol):       name: str; version: int
    def segment(self, text: str, llm: LLM) -> list[Segment]: ...
class SkillExtractor(Protocol):  name: str; version: int
    def extract(self, text: str, segments: list[Segment], llm: LLM) -> list[SkillItem]: ...
class SalaryExtractor(Protocol): name: str; version: int
    def extract(self, text: str, llm: LLM) -> list[SalaryItem]: ...
```

**How the contracts are used:**

- **Steps see only `LLM`, never Ollama.** Tests pass a scripted fake; the next change can pass the same client to CV steps.
- **The step registry** maps names to instances. `llm.segmenter` selects one.
- **`run_pipeline`** calls `should_stop()` between steps and raises `Cancelled` when it returns true. A step raises `StepFailed(step, message)` for errors that should be stored as a failed run.
- **The next change** (CV) adds a segmenter for ODT section structure and reuses the skill extractor and validator unchanged.

**Why spans rather than text.** If a segmenter could rewrite text (summarise or normalise it), quotes could no longer be checked and marks could no longer be highlighted. Offsets make that impossible by construction.

### D5. The steps

**`rules@1` segmenter.** A short line (under about 80 characters, with no final full stop) that matches a heading pattern starts a section.

| Heading patterns | Section label |
|---|---|
| requirements, qualifications, what you'll need or bring, must have, you have | required |
| preferred, nice to have, bonus, desired, ideally | preferred |
| any other heading | other |

Within a required section, a line containing "a plus", "preferred" or "nice to have" becomes preferred. It needs no model and is the baseline for eval.

**`llm-lines@1` segmenter.** Number the non-empty lines and ask for `[{line, label}]` with `label` from an enum.
- Lines the model omits are `other`.
- Out-of-range numbers are ignored.
- If the estimated tokens (characters ÷ 3.5) exceed 60% of `num_ctx`, the lines go in batches.

Returning line numbers instead of text keeps segments verbatim. This is the default segmenter.

**`atomic@1` skill extractor.**
- **One call per group** (required, then preferred), giving that group's lines numbered.
- **Output schema:** `[{line, name, kind, quote}]`, with instructions to split lists, use canonical names of 1–4 words, and give the shortest supporting quote.
- **Importance comes from the group, never from the model.** In the measured runs, the model's own required/preferred labelling was the least stable part.
- **Empty results.** If a group with at least one line returns nothing, retry once with a reminder message; a second empty result raises `StepFailed`.

**`paylines@1` salary extractor.**
- **Finding pay lines:** a regex matches currency symbols and codes, `k` amounts and pay words (salary, compensation, per hour, /yr). Lines that match are the only input; if there are none, the result is empty with no call.
- **Output schema:** `[{min, max, currency, period, location, basis, quote}]`, with `basis` from an enum.

**Validator.**
- **Normalising:** case-fold, collapse whitespace, and map typographic dashes and quotes to ASCII. A mapping from normalised to raw positions lets verified items store raw `start_offset`/`end_offset`.
- **Quotes** are searched first inside their source line, then anywhere in the text.
- **Amounts:** each amount must match a number in the quote after parsing `175,000`, `175000`, `175k` and `175K`, with a 0.5% tolerance.
- **Version:** the validator is versioned with the pipeline, because stricter checks change results.

### D6. The Ollama client and request options

`ollama.py` uses `urllib.request` with JSON bodies:

| Endpoint | Used for | Timeout |
|---|---|---|
| `/api/version` | reachability | 1.5 s |
| `/api/tags` | installed models | 1.5 s |
| `/api/show` | `capabilities`: text generation and thinking support, cached per model digest | 1.5 s |
| `/api/ps` | VRAM spill | 1.5 s |
| `/api/chat` | extraction | 600 s |

Each chat request sends:

```
stream: false, format: <schema>, keep_alive: "10m",
options: {temperature: 0, seed: 7, num_ctx: <setting>}, think: false (only when "thinking" in capabilities)
```

- A connection error raises `Unreachable`. The worker re-queues the job instead of failing it.
- An HTTP error or a body that fails schema parsing raises `StepFailed`.
- Status is cached in-process for 5 s, so pages that disable actions don't each wait for the timeout.

**Alternative considered:** the `ollama` Python package. Rejected because four endpoints don't justify a dependency, and the project records library choices deliberately.

### D7. The queue and worker

- **Enqueueing.** The job records `snapshot_id`, `model` and `pipeline` at enqueue time, so a settings change doesn't alter queued work. A partial uniqueness rule (one queued-or-running job per `job_id`) is enforced in `jobs.enqueue` inside the transaction, not with a database constraint, so it stays portable.
- **Worker loop:**
  1. Wait on a `threading.Event`, which `enqueue` sets, with a 5 s timeout.
  2. If Ollama is unreachable, sleep 10 s.
  3. Claim the oldest queued job (`UPDATE … WHERE id = :id AND status = 'queued'`).
  4. Run the pipeline outside any transaction.
  5. In one transaction, `derived.save_run` and set the job to done or failed. On `Cancelled`, mark the job cancelled and save nothing. On `Unreachable`, put the job back to queued.
- **Recovery.** At worker start, jobs left `running` go back to `queued`.
- **Starting.** `cli._serve` starts the worker after `create_app`. It skips the debug reloader's parent process: it starts only when `not args.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"`. `create_app` never starts it, so tests stay synchronous: they call `jobs.run_next(engine, llm)` directly.
- **Polling.** The queue fragment polls every 3 s through htmx while jobs are queued or running. When idle it returns status 286, which tells htmx to stop polling.
- **Cancelling.** Cancel marks queued jobs cancelled and sets a flag that the running job's `should_stop` reads. A chat call in progress finishes first, so cancelling takes at most one step (about 30 s).

**Alternative considered:** running extraction inside the request with an htmx spinner. Rejected because bulk extraction needs a queue anyway, a 30–75 s cold request ties up a server thread, and work would be lost on reload.

**Alternative considered:** a separate worker process or a task library (RQ, Celery). Rejected because it needs extra services for a single-user local tool.

### D8. The web layer

- **`create_app`** gains an `ollama` parameter: a client, or `None` when no URL is configured. Tests pass a fake.
- **Status badge:** in `base.html`, loaded with `hx-get="/llm/status" hx-trigger="load, every 15s"`, so a slow or unreachable Ollama never delays the page itself.
- **Settings:** `GET /settings` and `POST /settings`. The model list is filtered by `capabilities` containing `completion`.
- **Extraction:** `POST /postings/<id>/extract`. `POST /extract` queues the current list's unextracted postings; the list filters are passed as form fields, and the button label carries the count ("Extract 20 postings") with `hx-confirm`.
- **Queue:** `GET /llm/queue` and `POST /llm/queue/cancel`.
- **Suggestions:**
  - `POST /suggestions/<id>/accept`
  - `POST /postings/<id>/suggestions/accept-all` with `importance`
  - `POST /postings/<id>/rejections` and its delete
- **Labelled flag:** `POST /postings/<id>/labelled`.
- **The "Model says" panel** is filled from `queries.enrichment_panel(conn, job_id, run_id=None)`. Unverified items sit behind `<details>`. Every model string is autoescaped and never passed through `|safe`.
- **The mark popup** gains importance radio buttons (unspecified, required, preferred). `_marks.html` gains an importance select per mark, saved like the level, and the "labelling complete" toggle.

### D9. Evaluation

- **The set.** `evaluate.labelled_set(conn)` returns postings with `skills_complete_at` set, each grouped as blind (every mark has origin `selection`) or reviewed.
- **Runs.** For each posting, reuse the newest successful run for (latest snapshot, model, pipeline) unless `--fresh`. Otherwise run the pipeline synchronously (not through the queue) and save it through `derived.py`.
- **Reachability check.** Before any model call, check that Ollama is reachable if any run is needed. If not, exit with status 1 and write nothing.
- **Matching.**
  1. Pair suggestions and marks with equal skill keys.
  2. Then pair the rest whose spans overlap. A mark's span is its collapsed quote located in the latest snapshot through the validator's normalisation.
  
  Rejected suggestions count as unmatched.
- **Stage attribution.** Each mark's located span is also checked against the run's segments, read from the step trace in `output_json`. A mark is *reached* when its span overlaps a required or preferred segment. Every mark that no verified suggestion matches gets exactly one cause:
  - **segmenter miss:** the span is located but overlaps no required or preferred segment, so no extractor saw it
  - **extractor miss:** the span overlaps a required or preferred segment, but nothing matched it
  - **unlocated:** the quote is not found in the latest snapshot, so the step can't be told

  Only successful runs are attributed; failed runs are already counted as failures.
- **Report.** Precision, recall and importance agreement (all, required, preferred) for each group, plus segment recall (reached marks ÷ located marks), the miss count for each cause, the number of failures and the mean run time. Text by default; `--json` for scripts.

**Why blind and reviewed are separate:** labels made after seeing suggestions tend to agree with the model, which makes recall look better than it is.

**Why attribute misses:** end-to-end recall can't tell whether the segmenter or the extractor lost a skill, and the answer decides which step to change. Because importance is taken from segments, importance agreement already measures the segmenter's labels; segment recall measures its coverage. Both segmenters can then be compared on the same labelled set without reading traces by hand.

### D10. Safety

- **Untrusted text.** Posting text goes to the model as input. A prompt injected into a posting can only produce wrong suggestions: the model has no tools, its output is checked against the text, and nothing becomes user data without a click.
- **No proxying.** The Ollama URL comes only from the CLI or environment, so the browser can't turn the server into a proxy.
- **Read-only GET handlers.** `/llm/status` calls Ollama but writes nothing.
- **The guard is unchanged** and covers every new POST.

### D11. Testing

- **`FakeLLM`** returns scripted responses for each call, keyed by step, and records requests so tests can assert on schema, options and attempt counts.
- **The client** is tested against a stdlib `http.server` stub running in a thread: request options, `think` handling, timeouts and the unreachable case.
- **Pure tests** cover the segmenters, extractors, validator (dashes, `175k`, multiple ranges) and `run_pipeline`, including retry on empty and cancellation.
- **Engine-fixture tests,** run on SQLite and on Postgres when configured, cover:
  - `derived.save_run`
  - the queue: enqueue dedup, claim, recover, cancel, re-queue when unreachable
  - accept and reject
  - the labelled flag
  - `queries` read models
  - eval matching, metrics and miss attribution
  - re-import leaving runs, marks and rejections unchanged
- **Web tests** with a fake client cover the badge (offline, online, spill, missing model), settings, extract and queue fragments, accept and reject, escaped model output, and the guard on new POST routes.
- **`test_migrate.py`** must still report no schema differences, and the upgrade test checks that existing marks get `origin = 'selection'`.

## Risks / Trade-offs

- **[The rule segmenter fails on postings without headings]** → It is a baseline for eval, not the default. `llm-lines` is the default and either can be replaced.
- **[The line classifier mislabels a line, losing or mis-grading its skills]** → Importance is taken from segments only, so eval's importance agreement shows mis-graded lines directly, and segment recall with the segmenter-miss count shows lost lines. The segment trace in `output_json` shows which line went wrong.
- **[The model "corrects" a quote (typo fixed, words reordered), so it fails verification]** → It is kept and flagged, the user can show it, and eval reports the verification rate. Normalisation already absorbs dash, quote and whitespace differences.
- **[SQLite write contention between the worker and requests]** → Transactions are short (the model calls happen outside them) and there is one worker. SQLite's default busy timeout is enough for one user.
- **[The debug reloader starts two workers]** → Guarded by `WERKZEUG_RUN_MAIN`; covered by a CLI test.
- **[Switching models evicts the loaded one (20–45 s reload), and two large models don't fit in 16 GB]** → Jobs run in order and record their model, so a mixed queue reloads only when the model changes. The status badge shows spill.
- **[Cancelling waits for the current chat call]** → Bounded by one step (about 30 s warm); the UI shows "cancelling".
- **[A small labelled set (5–10 postings) gives noisy metrics]** → The report shows counts next to ratios, and reviewed postings add volume over time, reported separately.
- **[Float amounts]** → Acceptable for display and comparison. Amounts are not used in arithmetic that needs exact cents.

## Migration Plan

1. Revision `0003_llm_enrichment` adds the six new tables and three new columns. `origin` gets a server default of `selection`, so existing marks need no data step. `init_db` applies it on the next `import` or `serve`.
2. No backfill: postings have no runs until the user queues extraction.
3. **Rollback.** `downgrade()` drops the new tables and columns. This loses settings, runs, rejections, importances and labelled flags. As with `0002`, copy the database (or `pg_dump`) before downgrading; CLAUDE.md's backup note gains this revision.

## Open Questions

- Which segmenter and model should be the defaults once eval has numbers? Segment recall compares the segmenters directly. Both are settings, so changing them needs no spec or schema change.
- Should old `done` and `cancelled` jobs be pruned? They are small, so this can wait until the table is large enough to notice.
