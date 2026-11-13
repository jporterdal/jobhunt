# Tracing model work

jobhunt can send [OpenTelemetry](https://opentelemetry.io/) traces of its model work to a trace viewer running on
your machine, so you can see where a run's time went and how many tokens each step used. A trace shows one run
(a posting extraction, a document extraction, a links job) or one `jobhunt eval` as a timeline of its steps and
model calls.

Tracing is off unless you turn it on, it needs an optional extra, and spans go only to an address on this machine.
The rules are in the [`model-tracing` spec](../openspec/specs/model-tracing/spec.md).

## Turning it on

1. Install the extra into the project's venv:

   ```bash
   pip install -e ".[otel]"
   ```

2. Start a viewer (see [Jaeger](#jaeger) or [Langfuse](#langfuse-self-hosted) below).

3. Start `serve` or `eval` with the viewer's OTLP/HTTP traces address:

   ```bash
   jobhunt serve --otlp-endpoint http://localhost:4318/v1/traces
   jobhunt eval --otlp-endpoint http://localhost:4318/v1/traces
   ```

   or set `JOBHUNT_OTLP_ENDPOINT` to the same address. The option wins over the variable.

- The address is the **full traces URL** (ending in `/v1/traces` for Jaeger), passed to the exporter as it is.
- Only `http` or `https` addresses on `localhost`, `127.0.0.0/8` or `::1` are accepted. Anything else is refused
  with exit status 2 before the database is opened: traces are only sent to this machine.
- `OTEL_EXPORTER_OTLP_ENDPOINT` does **not** turn tracing on, so a variable set for another tool in the same shell
  never starts jobhunt exporting. `OTEL_EXPORTER_OTLP_HEADERS` is read by the exporter itself (Langfuse needs it).
- The address is fixed at start-up. The web interface can't read or change it.
- `serve` prints `tracing: <address>` with its other start-up lines when tracing is on. `eval` prints nothing extra
  on standard output, so its report is the same with or without tracing.
- With an address but without the extra, the command warns on standard error that tracing is off and how to install
  it, then runs as usual.
- Spans are sent in batches on a background thread, so a viewer that is slow, down or answering with errors never
  fails or slows a job. The exporter reports a missing viewer once on standard error. When the command stops it tries
  for up to 5 seconds to send the spans it still holds.

Without an address nothing changes: no span is made, the OpenTelemetry packages aren't even imported, and stored
results are exactly what they were before tracing existed.

## What is traced

| Span | Name | Inside |
|---|---|---|
| A command's root | `eval skills`, `eval links` | (the trace's root) |
| A run | `run posting`, `run document`, `run links` | the root, or nothing for a queue job |
| A step | `step segment`, `step skills`, `step salary`; `step sections`, `step lines`, `step records`, `step skills`, `step part_of`; `step expand`, `step embed`, `step judge` | its run |
| A model call | `chat <model>`, `embeddings <model>` | its step |

Each job of the queue is its own trace. `jobhunt eval` makes one trace holding a run span per **new** run;
`jobhunt eval --links` makes one trace holding one `run links` span. Results that are reused make no spans. A
links job has one `step judge` per posting skill sent to the model; a posting skill with nothing on its shortlist is
judged without a request and has no step. Importing, page views, recommendations, CV proposals and the prune are not
traced.

### Attributes

Names come from the OpenTelemetry GenAI semantic conventions where they have one (semantic conventions **1.44.0**,
as in `opentelemetry-semantic-conventions` 0.66b2; these names are still at "Development" stability and may be
renamed upstream), and start with `jobhunt.` otherwise. They are constants at the top of
`src/jobhunt/enrich/tracing.py`.

| Span | Attribute | Value |
|---|---|---|
| run | `jobhunt.run.kind` | `posting`, `document` or `links` |
| run | `jobhunt.run.origin` | `app` (the queue) or `eval` (`jobhunt eval`) |
| run | `jobhunt.run.status` | `succeeded`, `failed` or `cancelled` (absent when the server was unreachable: the job waits) |
| run | `gen_ai.request.model`, `jobhunt.pipeline` | the run's model and pipeline id |
| run | `jobhunt.job.id`, `jobhunt.posting.id`, `jobhunt.snapshot.id`, `jobhunt.document.id`, `jobhunt.run.id` | integer ids, when known (`jobhunt.run.id` once the result is stored; eval runs are stored later, so they have none) |
| run (links) | `jobhunt.embed_model`, `jobhunt.links.planned`, `jobhunt.links.judged`, `jobhunt.links.failed` | the embedding model and the pass's counts |
| step | `jobhunt.step.name`, `jobhunt.step.method` | the step and its method's `name@version` (`atomic@2`); for `step embed`, the embedding model |
| chat | `gen_ai.operation.name` (`chat`), `gen_ai.provider.name` (`ollama`), `gen_ai.request.model`, `gen_ai.request.temperature`, `gen_ai.request.seed`, `jobhunt.request.num_ctx` | the request's fixed options |
| chat | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | Ollama's `prompt_eval_count` and `eval_count` |
| chat | `jobhunt.ollama.total_duration_s`, `.load_duration_s`, `.prompt_eval_duration_s`, `.eval_duration_s` | Ollama's durations, in seconds |
| embeddings | `gen_ai.operation.name` (`embeddings`), `gen_ai.provider.name`, `gen_ai.request.model`, `jobhunt.embed.texts`, `jobhunt.embed.batches` | the number of texts and of requests |
| embeddings | `gen_ai.usage.input_tokens`, `jobhunt.ollama.total_duration_s`, `.load_duration_s` | summed over the call's requests |
| any failed span | status `ERROR`, `error.type` | `StepFailed`, `Unreachable`, `Cancelled` or the exception's class |

A count or duration Ollama leaves out of its answer (it omits `prompt_eval_count` when the prompt was cached) is left
off the span, not written as zero. Usage figures come from the real client only; with the test fakes the model call
spans exist but carry none. Latency is each span's own start and end. The resource names `service.name=jobhunt` and
`service.version` only: no host, user or process details.

### What spans never hold

By default spans hold no posting text, document text, prompt, model answer, quote, skill name, title, company name,
address, profile value or error message: only integer ids, method and model names, counts and durations. Errors are
named by their kind; no exception event is recorded, since its message can quote model output.

`--trace-content` (or `JOBHUNT_TRACE_CONTENT=1`), also fixed at start-up, adds:

- on each chat span, the system message (`gen_ai.system_instructions`), the user message (`gen_ai.input.messages`)
  and the answer (`gen_ai.output.messages`), as JSON text;
- on each judging step, the posting skill's key (`jobhunt.link.posting_key`);
- on failed spans, the error message as the status description.

Embedding spans never carry their texts. `serve` prints `span content: on` when content is on.

Content makes the viewer one more place that holds your CV and postings, outside `data/` and its backups. Jaeger as
run below keeps traces in memory, so they go when it stops; Langfuse keeps them in its Postgres and ClickHouse
databases and its MinIO object store (Docker volumes) until you delete them (`docker compose down -v` removes the
volumes).

## Finding a stored run's trace

A result stored while tracing is on names its trace inside its `output_json`, as
`"otel": {"trace_id": "<32 hex>", "span_id": "<16 hex>"}`: posting and document runs name their run span; link
judgments, link measurements and skill expansions name the step that made them (a judgment made without a request
names its run span). Results stored while tracing is off have no `otel` entry. Traces themselves are never stored in
the database.

The posting page shows the trace id after the run's model and pipeline (`trace 4bf92f3577b34da6a3ce929d0e0e4736`
in this invented example). Paste it into the viewer's trace search (Jaeger: the search box at the top of the UI) to
open the run. In the other direction, a queue job's run span carries `jobhunt.run.id`, the stored run's id.

## Jaeger

[Jaeger](https://www.jaegertracing.io/docs/latest/getting-started/) needs no account or key and keeps traces in
memory. Start the all-in-one container (Jaeger 2.23, checked 2026-11), publishing only the UI and OTLP/HTTP, and only
on this machine:

```bash
docker run --rm --name jaeger \
  -p 127.0.0.1:16686:16686 \
  -p 127.0.0.1:4318:4318 \
  cr.jaegertracing.io/jaegertracing/jaeger:2.23.0
```

Then:

```bash
jobhunt serve --otlp-endpoint http://localhost:4318/v1/traces
```

and open the UI at <http://localhost:16686>, choose the service `jobhunt` and click "Find Traces". Run jobhunt
where `localhost:4318` reaches the container (under WSL, that is wherever Docker publishes the port).

## Langfuse (self-hosted)

[Langfuse](https://langfuse.com/self-hosting/deployment/docker-compose) shows prompts and answers side by side, which
makes it most useful with `--trace-content`. Only a self-hosted instance on this machine passes the loopback check;
Langfuse's cloud does not. Its OpenTelemetry endpoint needs Langfuse 3.22.0 or later and accepts OTLP/HTTP with
protobuf, which is what jobhunt sends.

1. Start it with Docker Compose. Change every secret marked `# CHANGEME` in `docker-compose.yml` first:

   ```bash
   git clone https://github.com/langfuse/langfuse.git
   cd langfuse
   docker compose up
   ```

   After two or three minutes the `langfuse-web-1` container logs "Ready". Open <http://localhost:3000>, sign up
   (there is no default user), create a project and an API key pair.

2. Give the exporter the key pair as a Basic authorization header (`-w 0` keeps a long key on one line):

   ```bash
   export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $(printf '%s' 'pk-lf-...:sk-lf-...' | base64 -w 0),x-langfuse-ingestion-version=4"
   ```

   The `x-langfuse-ingestion-version=4` header makes spans appear at once on Langfuse's v4 data model; without it
   they can take up to ten minutes to show.

3. Start jobhunt with Langfuse's traces path:

   ```bash
   jobhunt serve --otlp-endpoint http://localhost:3000/api/public/otel/v1/traces --trace-content
   ```

The key pair is a secret: keep it out of the repository and of shell history you share.
