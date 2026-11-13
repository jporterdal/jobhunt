"""Optional OpenTelemetry tracing of model work (the model-tracing capability). The only module that imports
`opentelemetry`, and only once tracing is turned on (`setup` or, in tests, `install`).

With tracing off every helper is a pass-through: `chat` and `embed` just call the model, the context managers
yield a handle whose methods do nothing, `ids()` is None and `record_usage` does nothing. So nothing changes,
and nothing is imported, unless a command was started with a trace endpoint and the `otel` extra is installed.

Spans hold no text by default: no posting, document, prompt or answer text, no skill names and no error
messages, only integer ids, names of methods and models, counts and durations. `content=True`
(`--trace-content`) adds each chat call's messages and answer, a judging step's posting skill key, and failed
spans' error messages.

The module keeps its own provider and tracer and never sets OpenTelemetry's global provider.
"""

from __future__ import annotations

import contextvars
import json
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

# Attribute names. GenAI semantic conventions (Development stability) where they name one, as of semantic
# conventions 1.44.0 (opentelemetry-semantic-conventions 0.66b2); `jobhunt.*` otherwise. Renaming one is not a
# step or pipeline version change: spans are neither stored nor compared.
GEN_AI_OPERATION = "gen_ai.operation.name"
GEN_AI_PROVIDER = "gen_ai.provider.name"
GEN_AI_MODEL = "gen_ai.request.model"
GEN_AI_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_SEED = "gen_ai.request.seed"
GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_SYSTEM_INSTRUCTIONS = "gen_ai.system_instructions"
GEN_AI_INPUT_MESSAGES = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES = "gen_ai.output.messages"
ERROR_TYPE = "error.type"
PROVIDER = "ollama"

RUN_KIND = "jobhunt.run.kind"
STEP_NAME = "jobhunt.step.name"
STEP_METHOD = "jobhunt.step.method"
NUM_CTX = "jobhunt.request.num_ctx"
EMBED_TEXTS = "jobhunt.embed.texts"
EMBED_BATCHES = "jobhunt.embed.batches"
POSTING_KEY = "jobhunt.link.posting_key"  # content only

# What a run or root handle's set() accepts; anything else is a programming error (KeyError), so no text can be
# attached by passing a new keyword.
RUN_ATTRIBUTES = {
    "origin": "jobhunt.run.origin",
    "status": "jobhunt.run.status",
    "model": GEN_AI_MODEL,
    "pipeline": "jobhunt.pipeline",
    "job_id": "jobhunt.job.id",
    "posting_id": "jobhunt.posting.id",
    "snapshot_id": "jobhunt.snapshot.id",
    "document_id": "jobhunt.document.id",
    "run_id": "jobhunt.run.id",
    "embed_model": "jobhunt.embed_model",
    "planned": "jobhunt.links.planned",
    "judged": "jobhunt.links.judged",
    "failed": "jobhunt.links.failed",
}
RUN_STATUSES = ("succeeded", "failed", "cancelled")

# Ollama's answer fields -> attributes; durations are nanoseconds in the answer and seconds on the span.
USAGE_COUNTS = {"prompt_eval_count": GEN_AI_INPUT_TOKENS, "eval_count": GEN_AI_OUTPUT_TOKENS}
USAGE_DURATIONS = {
    "total_duration": "jobhunt.ollama.total_duration_s",
    "load_duration": "jobhunt.ollama.load_duration_s",
    "prompt_eval_duration": "jobhunt.ollama.prompt_eval_duration_s",
    "eval_duration": "jobhunt.ollama.eval_duration_s",
}

SHUTDOWN_SECONDS = 5
EXPORT_TIMEOUT_SECONDS = 5
INSTALL_HINT = 'pip install -e ".[otel]"'
# The exporter's and the batch processor's loggers: a missing viewer is reported once, not once per batch.
EXPORT_LOGGERS = ("opentelemetry.exporter.otlp.proto.http.trace_exporter", "opentelemetry.sdk._shared_internal",
                  "opentelemetry.sdk.trace.export")

_tracer = None
_content = False
_otel = None  # opentelemetry.trace, imported by install()
_model_span: contextvars.ContextVar = contextvars.ContextVar("jobhunt_model_span", default=None)


def enabled() -> bool:
    return _tracer is not None


def content() -> bool:
    """True when spans carry content (only while tracing is on)."""
    return _tracer is not None and _content


# --- Turning it on ---


def _noop() -> None:
    pass


class _Once:
    """A logging filter that lets the first warning or error through and drops the rest."""

    def __init__(self):
        self.seen = False

    def filter(self, record) -> bool:
        if self.seen:
            return False
        self.seen = True
        return True


def setup(endpoint: str | None, content: bool = False) -> Callable[[], None]:
    """Turn tracing on for this process, exporting to `endpoint` (an OTLP/HTTP traces address) in batches on the
    SDK's own thread; returns the shutdown, which sends what is left for at most SHUTDOWN_SECONDS. With no
    endpoint, or without the `otel` extra (a warning on stderr), tracing stays off and the shutdown does nothing."""
    if endpoint is None:
        return _noop
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        print(
            f"warning: tracing is off: the OpenTelemetry packages aren't installed (install them with {INSTALL_HINT})",
            file=sys.stderr,
        )
        return _noop
    import logging
    from importlib.metadata import PackageNotFoundError, version

    try:
        service_version = version("jobhunt")
    except PackageNotFoundError:
        service_version = "unknown"
    once = _Once()
    loggers = [logging.getLogger(name) for name in EXPORT_LOGGERS]
    for logger in loggers:
        logger.addFilter(once)
    # The resource is named here in full: no host, process or environment detectors.
    provider = TracerProvider(resource=Resource({"service.name": "jobhunt", "service.version": service_version}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=EXPORT_TIMEOUT_SECONDS)))
    install(provider, content)

    def shutdown() -> None:
        reset()
        closing = threading.Thread(target=provider.shutdown, name="jobhunt-trace-shutdown", daemon=True)
        closing.start()
        closing.join(SHUTDOWN_SECONDS)
        for logger in loggers:
            logger.removeFilter(once)

    return shutdown


def install(provider, content: bool = False) -> None:
    """Trace to `provider` (tests: an SDK provider with an in-memory exporter)."""
    global _tracer, _content, _otel
    from opentelemetry import trace

    _otel = trace
    _tracer = provider.get_tracer("jobhunt")
    _content = content


def reset() -> None:
    """Turn tracing off."""
    global _tracer, _content
    _tracer = None
    _content = False


# --- Handles ---


class _Off:
    """The handle yielded while tracing is off: every method does nothing."""

    recording = False

    def set(self, **attrs) -> None:
        pass

    def finish(self, status: str, error: str | None = None) -> None:
        pass

    def fail(self, exc: BaseException) -> None:
        pass


OFF = _Off()


def _message(exc: BaseException) -> str:
    return getattr(exc, "message", None) or str(exc)


def _error(span, kind: str, message: str | None) -> None:
    span.set_attribute(ERROR_TYPE, kind)
    span.set_status(_otel.Status(_otel.StatusCode.ERROR, message if _content else None))


class _Span:
    """A recording span's handle: set() run attributes, finish() a run with its outcome, fail() a step whose
    error was caught inside it."""

    recording = True

    def __init__(self, span):
        self.span = span
        self.finished = False

    def set(self, **attrs) -> None:
        for key, value in attrs.items():
            if value is not None:
                self.span.set_attribute(RUN_ATTRIBUTES[key], value)

    def finish(self, status: str, error: str | None = None) -> None:
        """The run's outcome: 'succeeded', 'failed' (a StepFailed error) or 'cancelled'."""
        if status not in RUN_STATUSES:
            raise ValueError(f"unknown run status {status!r}")
        self.finished = True
        self.set(status=status)
        if status == "failed":
            _error(self.span, "StepFailed", error)
        elif status == "cancelled":
            _error(self.span, "Cancelled", None)

    def fail(self, exc: BaseException) -> None:
        _error(self.span, type(exc).__name__, _message(exc))


@contextmanager
def _span(name: str, kind: str = "INTERNAL", run: bool = False) -> Iterator[_Span]:
    """A current span ended on exit. An exception passing through gives it an error status and `error.type` (the
    message only with content on; no exception event, whose message could quote model output) and is raised
    again unchanged. A run span also records 'cancelled' or 'failed' as its status."""
    with _tracer.start_as_current_span(
        name, kind=getattr(_otel.SpanKind, kind), record_exception=False, set_status_on_exception=False
    ) as span:
        handle = _Span(span)
        try:
            yield handle
        except BaseException as exc:
            kind_name = type(exc).__name__
            if run and not handle.finished:
                if kind_name == "Cancelled":
                    handle.set(status="cancelled")
                elif kind_name != "Unreachable":  # the job waits for the server: it neither failed nor finished
                    handle.set(status="failed")
            _error(span, kind_name, None if kind_name == "Cancelled" else _message(exc))
            raise


@contextmanager
def root(name: str) -> Iterator[_Span | _Off]:
    """A command's root span (`eval skills`, `eval links`)."""
    if _tracer is None:
        yield OFF
        return
    with _span(name) as handle:
        yield handle


@contextmanager
def run(kind: str, **attrs) -> Iterator[_Span | _Off]:
    """A run span (`run posting`, `run document`, `run links`) with RUN_ATTRIBUTES; the caller finishes it."""
    if _tracer is None:
        yield OFF
        return
    with _span(f"run {kind}", run=True) as handle:
        handle.span.set_attribute(RUN_KIND, kind)
        handle.set(**attrs)
        yield handle


@contextmanager
def step(name: str, method: str | None, posting_key: str | None = None) -> Iterator[_Span | _Off]:
    """A step span (`step skills`, …) naming the step's method (`atomic@2`). `posting_key` is content: it is
    attached only with content on."""
    if _tracer is None:
        yield OFF
        return
    with _span(f"step {name}") as handle:
        handle.span.set_attribute(STEP_NAME, name)
        if method is not None:
            handle.span.set_attribute(STEP_METHOD, method)
        if _content and posting_key is not None:
            handle.span.set_attribute(POSTING_KEY, posting_key)
        yield handle


@contextmanager
def _model_call(name: str, operation: str, model: str | None) -> Iterator[Any]:
    with _span(f"{name} {model}" if model else name, kind="CLIENT") as handle:
        span = handle.span
        span.set_attribute(GEN_AI_OPERATION, operation)
        span.set_attribute(GEN_AI_PROVIDER, PROVIDER)
        if model:
            span.set_attribute(GEN_AI_MODEL, model)
        token = _model_span.set(span)
        try:
            yield span
        finally:
            _model_span.reset(token)


def chat(llm, system: str, user: str, schema: dict) -> dict:
    """llm.chat_json(system, user, schema), inside a `chat <model>` span while tracing is on."""
    if _tracer is None:
        return llm.chat_json(system, user, schema)
    from .ollama import SEED, TEMPERATURE

    with _model_call("chat", "chat", getattr(llm, "model", None)) as span:
        span.set_attribute(GEN_AI_TEMPERATURE, TEMPERATURE)
        span.set_attribute(GEN_AI_SEED, SEED)
        if getattr(llm, "num_ctx", None) is not None:
            span.set_attribute(NUM_CTX, llm.num_ctx)
        if _content:
            span.set_attribute(GEN_AI_SYSTEM_INSTRUCTIONS, json.dumps([{"type": "text", "content": system}]))
            span.set_attribute(
                GEN_AI_INPUT_MESSAGES, json.dumps([{"role": "user", "parts": [{"type": "text", "content": user}]}])
            )
        answer = llm.chat_json(system, user, schema)
        if _content:
            span.set_attribute(GEN_AI_OUTPUT_MESSAGES, json.dumps([{
                "role": "assistant", "parts": [{"type": "text", "content": json.dumps(answer, ensure_ascii=False)}],
                "finish_reason": "stop",
            }]))
        return answer


def embed(client, model: str, texts: list[str]) -> list[list[float]]:
    """client.embed(model, texts), inside an `embeddings <model>` span while tracing is on. The span carries the
    number of texts, never the texts."""
    if _tracer is None:
        return client.embed(model, texts)
    with _model_call("embeddings", "embeddings", model) as span:
        span.set_attribute(EMBED_TEXTS, len(texts))
        return client.embed(model, texts)


def record_usage(response: dict, batches: int | None = None) -> None:
    """Put the counts and durations of an Ollama answer on the current model call span; fields the answer
    leaves out are left out. Does nothing outside a model call span (and so with tracing off)."""
    span = _model_span.get()
    if _tracer is None or span is None or not span.is_recording():
        return
    for field, name in USAGE_COUNTS.items():
        if isinstance(response.get(field), int):
            span.set_attribute(name, response[field])
    for field, name in USAGE_DURATIONS.items():
        if isinstance(response.get(field), int):
            span.set_attribute(name, response[field] / 1e9)
    if batches is not None:
        span.set_attribute(EMBED_BATCHES, batches)


def ids() -> dict | None:
    """{"trace_id": 32 hex, "span_id": 16 hex} of the current span while one is recording, else None."""
    if _tracer is None:
        return None
    span = _otel.get_current_span()
    if not span.is_recording():
        return None
    context = span.get_span_context()
    return {"trace_id": format(context.trace_id, "032x"), "span_id": format(context.span_id, "016x")}


def with_ids(output: dict) -> dict:
    """`output` with an "otel" entry naming the current span, added last; `output` itself when there is none."""
    current = ids()
    return output if current is None else {**output, "otel": current}
