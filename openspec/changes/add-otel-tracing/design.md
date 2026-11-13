## Context

See proposal.md for the motivation. What the code looks like today, as far as it shapes the design:

- **Posting runs:** `pipeline.run_pipeline` runs three steps through its inner `step()`, which gives each a `_Recorder`; `_Recorder.chat_json` times every call and keeps the answer for `output_json`. The run doesn't know its origin: the caller passes `app` or `eval` to `derived.save_run` afterwards.
- **Document runs:** `cv.run_document` has its own `step()`, which returns a `_Recorder` and has no end: a step lasts until the next one starts.
- **Link judging:** `links.judge_links` (and `link_eval.execute`, `expand.expand_all`) call `llm.chat_json` and `client.embed` directly, with no recorder.
- **The client:** `ChatModel.chat_json` returns only the parsed answer, so `prompt_eval_count`, `eval_count` and the `*_duration` fields of Ollama's response are dropped inside `ollama.py`. `OllamaClient.embed` makes one request per 64 texts.
- **Callers:** the worker saves each posting and document run right after it finishes (`jobs._run_posting`, `_run_document`). `evaluate.execute` makes all its runs first and saves them in one transaction at the end, so a run's id doesn't exist while the run is in progress.
- **Tests:** `FakeLLM` and `FakeOllama` stand in for `ChatModel` and `OllamaClient`; only `tests/test_ollama.py` runs the real client, against a stdlib HTTP stub.
- **Start-up options:** `cli._ollama_arg` is the model for a start-up-only address (`--ollama-url`, `$JOBHUNT_OLLAMA_URL`).

## Goals / Non-Goals

**Goals:**

- Span code in one small module, with every call site a one-line context manager or call.
- The same spans from the fakes as from the real client, so tests need no Ollama; only the usage figures need the real client.
- No import of `opentelemetry` anywhere when tracing is off, and no behaviour change.

**Non-Goals:**

- Metrics, logs, or spans for web requests, imports, SQL or the prune.
- Auto-instrumentation packages (`opentelemetry-instrument`, Flask or urllib instrumentation).
- Bundling, starting or checking a collector or viewer.
- A trace viewer or trace links inside the web UI beyond showing the trace id.
- Trace context propagation to Ollama (no `traceparent` header on its requests).

## Decisions

### D1. One module, `enrich/tracing.py`, owns OpenTelemetry

It is the only module that imports `opentelemetry`, and it imports it inside `setup()`. Its surface:

| Call | Used by | Does |
|---|---|---|
| `setup(endpoint, content=False)` | `cli._serve`, `cli._eval`, `cli._eval_links` | Builds a `TracerProvider` with a `BatchSpanProcessor` and the OTLP/HTTP exporter; returns a `shutdown()` that flushes for at most 5 s. Returns a no-op `shutdown` when the endpoint is `None`; warns and does the same when the packages are missing. |
| `install(provider, content=False)` / `reset()` | tests | Uses a given provider (in-memory exporter, `SimpleSpanProcessor`). |
| `root(name)` | `jobhunt eval` | The command's root span. |
| `run(kind, **attrs)` | `jobs._run_*`, `evaluate.execute`, `link_eval.execute` | Run span; the yielded handle has `set(**attrs)` and `finish(status)`. |
| `step(name, impl_id)` | `run_pipeline`, `run_document`, `judge_links`, `link_eval`, `expand_all` | Step span. |
| `chat(llm, system, user, schema)` | `_Recorder.chat_json`, `LinkJudge.judge`, `SkillExpander.expand` | Opens the chat span, calls `llm.chat_json`, returns the answer. |
| `embed(client, model, texts)` | `judge_links`, `link_eval.execute` | Opens the embedding span and calls `client.embed`. |
| `record_usage(response)` | `ChatModel.chat_json`, `OllamaClient.embed` | Writes Ollama's counts and durations to the current span. |
| `ids()` | where an output dict is built | `{"trace_id", "span_id"}` of the current span, or `None`. |

With tracing off every one of these is a plain pass-through (`chat` is `llm.chat_json(...)`, the context managers yield a handle whose methods do nothing, `ids()` is `None`).

The module keeps its own provider and tracer; it never calls `trace.set_tracer_provider`. OpenTelemetry lets the global provider be set once per process, which would make tests order-dependent, and nothing else in the process needs it.

*Alternative considered:* depending on `opentelemetry-api` always (its no-op tracer makes the calls free) and only the SDK as an extra. Rejected: the constraint is no new required dependency, and the pass-through is a few lines.

### D2. The model call span is opened at the call site; usage is added by the client

The chat span has to exist with the fakes, and the token counts exist only inside `ChatModel.chat_json`. So `tracing.chat` opens the span around `llm.chat_json`, and the real client calls `tracing.record_usage(response)` on the raw response, which sets attributes on whatever span is current. With a fake there is a chat span without usage; with the real client and no span (tracing off) `record_usage` does nothing.

`OllamaClient.embed` sums the figures of its batches and records them once, with the batch count, so an embedding call is one span however many requests it makes.

*Alternatives considered:* (a) returning usage from `chat_json`: changes the `LLM` protocol, every step and both fakes. (b) spans only inside `ollama.py`: the fakes would emit no model call spans, so the span tree couldn't be tested without an HTTP stub.

### D3. Callers open the run span; the run functions open step spans

`run_pipeline` and `run_document` don't know the origin, the job or the ids, and the worker can only attach the stored run's id if the span is still open at `save_run`. So:

- `jobs._run_posting` / `_run_document` / `_run_links` wrap the run and its save in `tracing.run(...)`, with origin `app`, the `llm_jobs` id and the posting or document id, and set the stored run's id after saving.
- `evaluate.execute` wraps each `run_pipeline` call in `tracing.run("posting", origin="eval", ...)`. The runs are saved later in one transaction, so these spans have no run id; the stored run names the span instead (D6).
- `link_eval.execute` opens one `links` run span with origin `eval` around its expansion, embedding and judging.
- `jobhunt eval` opens `tracing.root("eval skills")` or `tracing.root("eval links")` around planning and executing; the worker opens no root, so each job is its own trace.

`cv.run_document`'s `step()` becomes a context manager (as `run_pipeline`'s effectively is), so a step span ends where its step ends. This is the one structural edit; the stored trace is unchanged.

`Cancelled` and `Unreachable` pass through the context managers: the run span ends with status `cancelled`, or with an error of kind `Unreachable`, and the exception is raised again unchanged.

Span names and kinds:

| Span | Name | Kind |
|---|---|---|
| root | `eval skills`, `eval links` | internal |
| run | `run posting`, `run document`, `run links` | internal |
| step | `step <name>` (`step skills`, `step judge`, …) | internal |
| chat | `chat <model>` | client |
| embedding | `embeddings <model>` | client |

### D4. Attributes

GenAI semantic convention names where one exists. They are at "Development" stability, so they sit as constants at the top of `tracing.py`, and `docs/tracing.md` records the convention version they were taken from. Renaming one later is not a pipeline or step version change: spans aren't compared or stored.

| Span | Attribute | From |
|---|---|---|
| run | `jobhunt.run.kind`, `jobhunt.run.origin`, `jobhunt.run.status` | caller |
| run | `gen_ai.request.model`, `jobhunt.pipeline` | the job or plan |
| run | `jobhunt.job.id`, `jobhunt.posting.id`, `jobhunt.snapshot.id`, `jobhunt.document.id`, `jobhunt.run.id` | integers, when known |
| run (links) | `jobhunt.embed_model`, `jobhunt.links.planned`, `.judged`, `.failed` | `Pass` |
| step | `jobhunt.step.name`, `jobhunt.step.method` (`atomic@2`) | the step |
| chat | `gen_ai.operation.name`=`chat`, `gen_ai.provider.name`=`ollama`, `gen_ai.request.model`, `gen_ai.request.temperature`, `gen_ai.request.seed`, `jobhunt.request.num_ctx` | `llm.model`, `llm.num_ctx`, constants |
| chat | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | `prompt_eval_count`, `eval_count` |
| chat | `jobhunt.ollama.total_duration_s`, `.load_duration_s`, `.prompt_eval_duration_s`, `.eval_duration_s` | Ollama's nanoseconds ÷ 1e9 |
| embedding | `gen_ai.operation.name`=`embeddings`, `gen_ai.request.model`, `jobhunt.embed.texts` (count), `jobhunt.embed.batches`, input tokens, total and load durations | `client.embed` |
| any failed | status `ERROR`, `error.type` (`StepFailed`, `Unreachable`, `Cancelled`, or the exception class) | the failure |

Latency is the span's own duration; no attribute repeats it. A field Ollama leaves out (it omits `prompt_eval_count` for a cached prompt) is left out.

Exceptions are not recorded with `record_exception`: its event carries the message, which can quote model output. The message goes on the span only with content on (D5).

The resource is `service.name=jobhunt` and `service.version` only; no host, user or process detectors are added.

### D5. Content is opt-in, at start-up, chat only

`--trace-content` / `$JOBHUNT_TRACE_CONTENT=1` on `serve` and `eval`. With it, a chat span carries `gen_ai.system_instructions`, `gen_ai.input.messages` and `gen_ai.output.messages` (JSON text), a judging step carries `jobhunt.link.posting_key`, and failed spans carry the error message as the status description.

Offered because it stays on this machine (D7), the answers are already stored in `output_json`, and a viewer such as Langfuse shows little without it. Off by default because a viewer's storage is one more place holding CV and posting text, outside `data/` and its backups. Embedding texts are never sent: they add nothing a count doesn't.

### D6. A stored result names its trace, inside `output_json`

When a recording span is current, the code that builds a result's output adds `"otel": {"trace_id": "<32 hex>", "span_id": "<16 hex>"}`: `run_pipeline` and `run_document` to their trace (the run span's ids), and the judging, measuring and expanding loops to their output (the step span's ids). `derived.py` stays the only writer and stores what it is given; no column, no migration. With tracing off the key is absent, so stored output is byte-for-byte today's, and the demo's rows don't change.

The other direction: the worker sets `jobhunt.run.id` on the run span after `save_run` / `save_document_run`.

`llm/_panel.html` shows `trace <id>` after the model and pipeline when the run's output has one (`queries` already loads the run; it gains the id). Nothing else reads the key; `evaluate`'s reading of `output_json` for miss attribution ignores it.

*Alternatives considered:* a `trace_id` column on each derived table (five tables and a migration for a value only a developer reads); only the span attribute (a viewer would have to be searched by run id, and eval runs have no id while their span is open).

### D7. Endpoint: explicit, loopback, OTLP/HTTP

`--otlp-endpoint`, else `$JOBHUNT_OTLP_ENDPOINT`, else off, added to `serve` and `eval` by one `_tracing_args` helper beside `_ollama_arg`. The value is the full traces URL (`http://localhost:4318/v1/traces`) and is passed to the exporter as is. `cli` checks it before anything else: scheme `http` or `https`, host `localhost`, in `127.0.0.0/8`, or `::1`; otherwise `parser.error`, exit 2.

- **Loopback is enforced, not just documented.** The Ollama URL isn't restricted, but a span endpoint is a place data is pushed to, and the project's rule is that no data leaves the machine. A collector elsewhere on a LAN is out of scope until someone needs it.
- **`OTEL_EXPORTER_OTLP_ENDPOINT` doesn't turn tracing on.** A variable set for another tool in the same shell must not start jobhunt exporting. `OTEL_EXPORTER_OTLP_HEADERS` is left to the exporter, which reads it itself; a self-hosted Langfuse needs it for its API key.
- **OTLP/HTTP, not gRPC:** `opentelemetry-exporter-otlp-proto-http` avoids the `grpcio` dependency, and Jaeger and Langfuse both accept it.

`serve` prints `tracing: <endpoint>` (and `span content: on`) with its other start-up lines; `eval` prints nothing extra on stdout (its report must stay unchanged) and warnings go to stderr.

### D8. One setup for the worker and `jobhunt eval`

Both call `tracing.setup(args.otlp_endpoint, args.trace_content)` and call the returned `shutdown()` in their `finally`. `serve` calls it under the same guard as the worker (not in the debug reloader's parent), so the parent never exports. A `BatchSpanProcessor` in both: export happens on its own thread, so a dead endpoint costs the model work nothing, and `shutdown()` flushes what is left, bounded at 5 s, so `eval` neither loses its last spans nor hangs on a dead endpoint. The exporter's own failures are logged by the SDK; `setup` lowers that logger so a missing viewer prints one warning, not one per batch.

`create_app` never calls `setup`, as it never starts the worker; `jobhunt demo` doesn't either.

### D9. Viewer: documented, not bundled

`docs/tracing.md` gives:

- **Jaeger** as the default: the all-in-one container with OTLP/HTTP on 4318 and the UI on 16686, and the matching `--otlp-endpoint`. No account, no key, in-memory by default, so traces vanish when it stops.
- **Langfuse** (self-hosted) as the option for reading prompts and answers: its OTLP traces path and the `OTEL_EXPORTER_OTLP_HEADERS` value for its key, with `--trace-content`. Only a self-hosted instance on this machine passes the loopback check.
- The attribute table (D4), the convention version, and how to find a stored run's trace (D6).

Commands and paths are checked against each project's current documentation while writing the page, not copied from this design.

### D10. Tests

`tests/test_tracing.py`, skipped as a module when `opentelemetry.sdk` isn't importable (`pytest.importorskip`), uses `tracing.install` with `InMemorySpanExporter`:

- span tree and attributes for a posting run, a document run and a links job, driven by `FakeLLM` / `FakeOllama` and `jobs.run_next`;
- failed, cancelled and unreachable runs;
- `evaluate.execute` and `link_eval.execute`: root span, origin `eval`, no spans for reused results;
- the default-content check: no span string contains any text of the posting, document, prompt or answer; and the opt-in adds them;
- `otel` ids in stored output, `jobhunt.run.id` on the span, and the posting page showing the id;
- same requests with tracing on and off (`FakeLLM.requests` compared).

`tests/test_ollama.py` gains usage attributes through the HTTP stub (present, and absent when the stub omits a field). Tests that need no SDK, in the existing files: tracing off stores no `otel` key; a missing package with an endpoint warns and carries on (the import is made to fail); the endpoint check's accepted and refused values; the option and environment precedence.

CI installs `.[dev,otel]` (and `.[dev,postgres,otel]`) so the tracing tests run on every job; the lint and privacy jobs are unchanged.

## Risks / Trade-offs

- **GenAI convention names change** (they are experimental) → constants in one place, the version recorded in the docs, and no stored data depends on them.
- **A viewer keeps prompts and CV text when content is on** → off by default, start-up only, printed at start-up, loopback only, and the docs say where each viewer keeps its data.
- **`output_json` differs with tracing on**, so two otherwise identical runs aren't byte-equal → nothing compares stored output across runs; the key is absent with tracing off, which is how tests and the demo run.
- **Span calls spread over eight modules** → each is one line through `tracing.py`, and the same-requests test guards against a call site changing behaviour.
- **Loopback-only blocks a collector in another container network or on another host** → deliberate; `localhost` port publishing covers Docker and WSL. Relaxing it is a later, explicit change.
- **An evaluation is one large trace** (hundreds of spans) → what a per-command timeline needs, and within what Jaeger and Langfuse display; `--links` runs are the largest.
- **The SDK and exporter versions drift** → the extra sets lower bounds from the versions installed when implementing, and CI runs the tracing tests on both Python versions.

## Migration Plan

No schema or data migration. Existing installs are unaffected until they install the extra and pass an endpoint. Rollback is removing the option or the extra; stored `otel` ids are inert.

## Open Questions

- Whether the application and document pages should show a document run's trace id too. The posting page is enough to find a trace; adding it elsewhere is a template line each and changes nothing above.
