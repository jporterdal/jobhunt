## 1. The extra and the tracing module

- [ ] 1.1 Add the `otel` extra to `pyproject.toml` (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, lower bounds from the versions pip resolves now) and install it into `venv/`; verify `venv/bin/python -c "import opentelemetry.sdk, opentelemetry.exporter.otlp.proto.http"` succeeds and `pip install -e ".[dev]"` in a scratch venv still installs no OpenTelemetry package
- [ ] 1.2 Create `enrich/tracing.py` with the pass-through surface of D1 (`setup`, `install`, `reset`, `root`, `run`, `step`, `chat`, `embed`, `record_usage`, `ids`) and no top-level `opentelemetry` import; verify with tests (no SDK needed) that with tracing off `chat` returns the model's answer, the context managers yield handles whose methods do nothing, `ids()` is `None`, and `sys.modules` gains no `opentelemetry` module
- [ ] 1.3 Implement `setup` (own provider, `BatchSpanProcessor`, OTLP/HTTP exporter, resource `service.name`/`service.version`, `shutdown` bounded at 5 s, exporter logger lowered) and the missing-package warning (D1, D8); verify with tests that a failed import warns once naming `pip install -e ".[otel]"` and returns a no-op `shutdown`, and that `setup(None)` creates nothing
- [ ] 1.4 Implement the spans behind `install`: names, kinds, attribute constants, error status with `error.type` and no message, content attributes only when content is on (D3, D4, D5); verify in `tests/test_tracing.py` (module skipped without the SDK) with `InMemorySpanExporter` that each helper produces the span, parentage and attributes of the D3 and D4 tables

## 2. Model calls

- [ ] 2.1 Route `_Recorder.chat_json`, `LinkJudge.judge` and `SkillExpander.expand` through `tracing.chat`; verify one `chat <model>` span per request with `FakeLLM`, including the retry after an empty skills answer, and that `FakeLLM.requests` is identical with tracing on and off
- [ ] 2.2 Call `tracing.record_usage` in `ChatModel.chat_json` and, summed over batches with the batch count, in `OllamaClient.embed` (D2); verify in `tests/test_ollama.py` through the HTTP stub that counts and durations (seconds) appear on the current span, that a field the stub omits is absent, and that with no span the client behaves as before. Nanosecond durations in these tests must not be 9 or 10 digits long (the privacy check's posting ID pattern matches those): use values under 0.1 s or of 10 s and more, or build them at runtime
- [ ] 2.3 Route `client.embed` in `links.judge_links` and `link_eval.execute` through `tracing.embed`; verify one `embeddings <model>` span with the text count and no texts, using `FakeOllama`

## 3. Runs and steps

- [ ] 3.1 Open step spans in `run_pipeline`'s `step()` and add the `otel` ids to its trace when a span is recording (D6); verify the three step spans with their `name@version`, and that a run with tracing off stores `output_json` without an `otel` key and equal to today's for the same fake answers
- [ ] 3.2 Make `cv.run_document`'s `step()` a context manager, open step spans for its five steps and add the `otel` ids to its trace; verify the existing document tests pass unchanged and the five step spans end in order with the chat spans under `lines`, `skills` and `part_of`
- [ ] 3.3 Open the run span in `jobs._run_posting` and `_run_document` around the run and its save, with origin `app`, the job, posting or document, snapshot, model and pipeline, and set `jobhunt.run.id` after saving; verify through `jobs.run_next` the attributes and final status for a succeeded, a failed, a cancelled and an unreachable job, and that the job's outcome and stored rows match a run without tracing
- [ ] 3.4 Trace the links job: run span in `jobs._run_links`, steps for expansion, embedding and one `step judge` per posting skill with candidates, the `Pass` counts on the run span, and the `otel` ids in each judgment's and expansion's output; verify with `FakeOllama` that a job embedding new names and judging keys with and without candidates gives the tree of the spec's "A links job" scenario and no span for an empty shortlist
- [ ] 3.5 Trace `evaluate.execute` (a run span with origin `eval` per new run) and `link_eval.execute` (one `links` run span with origin `eval`, steps as in 3.4, ids in each measurement's output); verify that reused runs and judgments emit no spans and that each stored eval run's `otel.span_id` is its own run span's

## 4. Start-up options

- [ ] 4.1 Add `_tracing_args` (`--otlp-endpoint`, `$JOBHUNT_OTLP_ENDPOINT`; `--trace-content`, `$JOBHUNT_TRACE_CONTENT=1`) to `serve` and `eval`, with the loopback and scheme check as an argparse error (D7); verify with CLI tests that `http://localhost:4318/v1/traces`, `http://127.0.0.1:4318/v1/traces` and `http://[::1]:4318/v1/traces` are accepted, that `https://traces.example.com/v1/traces`, `http://192.0.2.10:4318/v1/traces` and `ftp://localhost/x` exit 2 before the database is opened, and that the option wins over the environment
- [ ] 4.2 Call `tracing.setup` and its `shutdown` in `_serve` (under the worker's reloader guard, printing `tracing:` and `span content: on` lines), `_eval` (inside `tracing.root("eval skills")`) and `_eval_links` (`tracing.root("eval links")`); verify with CLI tests that `eval`'s stdout report is identical with and without tracing, that the root span holds the run spans, and that `serve`'s start-up output names the endpoint only when tracing is on
- [ ] 4.3 Verify nothing in `web/` reads or sets the endpoint or the content flag: a test posts `otlp_endpoint` to `/settings` and checks no setting is stored and `tracing` state is unchanged

## 5. Showing the trace id

- [ ] 5.1 Give the posting panel's run its trace id (`queries`, from the run's `output_json`) and show `trace <id>` after the model and pipeline in `llm/_panel.html`, marked `.src-derived`; verify with web tests that a run made with tracing on shows its id and a run made without shows nothing

## 6. Content and privacy

- [ ] 6.1 Add the default-content test: run a posting job, a document job and a links job with tracing on and content off, then check that no span name, attribute value, status description or event contains any line of the posting or document, any prompt, any answer, any skill name or the error message of a failed step; verify it fails if a text attribute is added by mistake (try one locally, then remove it)
- [ ] 6.2 Add the opt-in tests: with content on, chat spans carry the system and user messages and the answer, a judging step carries its posting key, a failed span carries the message, and embedding spans still carry no texts

## 7. Docs, CI and checks

- [ ] 7.1 Write `docs/tracing.md` (D9): turning tracing on, the Jaeger and self-hosted Langfuse set-ups with commands checked against their current documentation, the attribute table with the GenAI convention version, `--trace-content` and where a viewer keeps data, finding a stored run's trace; verify every command in it against `jobhunt serve --help` and `jobhunt eval --help`, that it uses only fictional data, and that any example Ollama response in it has no 9- or 10-digit duration (the privacy check reports those as posting IDs)
- [ ] 7.2 Update CLAUDE.md (libraries and the optional extra, `enrich/tracing.py` in the architecture, a short "Tracing" paragraph under model enrichment, the new options under Commands, the install line) and link `docs/tracing.md` from the README; verify the commands listed match `--help`
- [ ] 7.3 Install the `otel` extra in the CI test jobs (`.github/workflows/ci.yml`); verify locally that `pytest` passes both with the extra installed and in a scratch venv without it (tracing tests skipped, everything else passing)
- [ ] 7.4 With the user watching and only after they agree to model use: start a local Jaeger as `docs/tracing.md` describes, run `jobhunt serve --otlp-endpoint …` against a **copy** of the database, extract one posting, and verify the trace appears with its run, step and chat spans, token counts and the id shown on the posting page; record what was seen in design.md
- [ ] 7.5 Run `pytest`, `JOBHUNT_TEST_PG_URL=… pytest` on Postgres, `ruff check`, `jobhunt privacy-check` and `openspec validate add-otel-tracing --strict`, and verify all pass
