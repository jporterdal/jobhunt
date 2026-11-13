## Why

Model work is the slow and opaque part of jobhunt. Each stored run keeps its step timings and raw answers in `output_json`, but nothing shows a run, a links job or a whole `jobhunt eval` as a timeline, and the token counts and durations Ollama returns with every answer are thrown away. Emitting OpenTelemetry traces lets a local viewer answer "where did the time go" and "how many tokens did this step use" without new tables or pages.

## What Changes

- Model work emits OpenTelemetry spans: one per run (a posting run, a document run, a links job), one per step, and one per model call (chat and embedding). `jobhunt eval` and `jobhunt eval --links` emit the same spans under one root span per command.
- Spans carry the model, pipeline id, step `name@version`, run origin (`app` or `eval`), status, and the token counts and durations Ollama returns, named after the OpenTelemetry GenAI semantic conventions (`gen_ai.*`, still experimental) where they have a name and `jobhunt.*` otherwise.
- Tracing is off unless a trace endpoint is given at start-up: `--otlp-endpoint` on `serve` and `eval`, else `$JOBHUNT_OTLP_ENDPOINT`, with no default. The endpoint must be on this machine (loopback); anything else is refused. It is never taken from the browser or the settings page.
- The OpenTelemetry SDK is a new optional extra (`pip install -e ".[otel]"`). Without it, or without an endpoint, tracing does nothing and behaviour is unchanged.
- Spans hold no posting, CV, prompt or answer text, no skill names and no error message text by default. `--trace-content` (or `$JOBHUNT_TRACE_CONTENT=1`), also start-up only, adds each chat call's messages and answer.
- A stored model result made while tracing is on records its trace id inside its `output_json`, and the posting page shows it beside the run's model and pipeline, so a stored run can be found in the viewer. Traces themselves are never stored in the database.
- `docs/tracing.md` explains running a local viewer (Jaeger, or a self-hosted Langfuse); none is bundled or started by jobhunt.

## Capabilities

### New Capabilities
- `model-tracing`: optional OpenTelemetry tracing of model work: when it is on, where spans go, which spans and attributes exist, what they never contain, and how a stored run names its trace.

### Modified Capabilities
- `llm-connection`: "Background job queue" says queue processing does nothing except call the configured Ollama address and store results; it now also allows sending spans to the configured trace endpoint.

## Parser impact

None: see [parser-impact.md](parser-impact.md).

## Impact

- **Code:** new `enrich/tracing.py` (the only module that imports `opentelemetry`); span calls in `enrich/pipeline.py`, `enrich/cv.py`, `enrich/links.py`, `enrich/expand.py`, `enrich/ollama.py`, `enrich/jobs.py`, `enrich/evaluate.py`, `enrich/link_eval.py`; options in `cli.py`; one line in `web/templates/llm/_panel.html`.
- **Dependencies:** optional extra `otel` (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`). No new required dependency.
- **Data:** no schema change and no migration. `output_json` of results made with tracing on gains an `otel` object; results made with tracing off are byte-for-byte what they are today.
- **Network:** with tracing on, `serve` and `eval` send spans to one loopback address besides Ollama.
- **Docs and CI:** `docs/tracing.md`, CLAUDE.md, and the `otel` extra installed in CI so the tracing tests run.
