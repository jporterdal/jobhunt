"""Scripted stand-ins for the model, so pipeline, queue and web tests never need Ollama."""

from __future__ import annotations

from dataclasses import dataclass

from jobhunt.demo.scripted import trigram_vector
from jobhunt.enrich.pipeline import Unreachable


@dataclass
class Request:
    key: str  # the schema's top-level field: "lines" (segment), "skills" or "ranges" (salary)
    system: str
    user: str
    schema: dict
    model: str | None
    num_ctx: int


class FakeLLM:
    """Answers each call from a per-step script, keyed by the schema's top-level field.

    A script is a list of responses used in order, the last one repeating; a response is a dict, or a
    callable taking the user message. With no script the answer is an empty list.
    """

    def __init__(self, responses: dict | None = None, num_ctx: int = 8192, unreachable: bool = False, on_call=None):
        self.responses = {key: list(script) for key, script in (responses or {}).items()}
        self.num_ctx = num_ctx
        self.unreachable = unreachable
        self.on_call = on_call
        self.model: str | None = None
        self.requests: list[Request] = []

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        if self.unreachable:
            raise Unreachable("connection refused")
        key = schema["required"][0]
        self.requests.append(Request(key, system, user, schema, self.model, self.num_ctx))
        if self.on_call is not None:
            self.on_call(key)
        script = self.responses.get(key)
        if not script:
            return {key: []}
        response = script.pop(0) if len(script) > 1 else script[0]
        return response(user) if callable(response) else response

    def calls(self, key: str) -> int:
        return sum(r.key == key for r in self.requests)

    # The client side used by the queue: bind a model, check reachability.
    def for_model(self, model: str, num_ctx: int) -> FakeLLM:
        self.model, self.num_ctx = model, num_ctx
        return self

    def version(self) -> str:
        if self.unreachable:
            raise Unreachable("connection refused")
        return "0.0-fake"


def label_lines(labels: dict[str, str]):
    """A segment response labelling each numbered line whose text contains a key."""

    def respond(user: str) -> dict:
        out = []
        for row in user.splitlines():
            number, _, text = row.partition(": ")
            for needle, label in labels.items():
                if needle in text:
                    out.append({"line": int(number), "label": label})
                    break
        return {"lines": out}

    return respond


def skill(line: int, name: str, quote: str, kind: str = "technical") -> dict:
    return {"line": line, "name": name, "kind": kind, "quote": quote}


class FakeOllama(FakeLLM):
    """The web interface's client: status, installed models, chat and embeddings, all scripted."""

    def __init__(self, state: str = "online", models=None, detail: str | None = None, vectors=None, **kwargs):
        """`vectors` maps a name (without its task prefix) to the embedding to answer with; others get trigrams."""
        from jobhunt.enrich.ollama import ModelInfo

        super().__init__(unreachable=state == "offline", **kwargs)
        self.vectors = vectors or {}
        self.url = "http://127.0.0.1:11434"
        self.state = state
        self.detail = detail
        self.installed = models if models is not None else [
            ModelInfo("gemma4:12b", "d1", 8_000_000_000, ("completion", "thinking")),
            ModelInfo("phi4:latest", "d2", 9_000_000_000, ("completion",)),
            ModelInfo("nomic-embed-text:latest", "d3", 270_000_000, ("embedding",)),
        ]
        self.status_calls = 0
        self.embed_requests: list[tuple[str, list[str]]] = []
        self.embed_failure: str | None = None

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Deterministic trigram vectors; `embed_failure` makes the call fail as a short response would."""
        from jobhunt.enrich.pipeline import StepFailed

        if self.unreachable:
            raise Unreachable("connection refused")
        self.embed_requests.append((model, list(texts)))
        if self.embed_failure:
            raise StepFailed("embed", self.embed_failure)
        names = [t.removeprefix("clustering: ") for t in texts]
        return [self.vectors[n] if n in self.vectors else trigram_vector(n) for n in names]

    def models(self):
        if self.unreachable:
            raise Unreachable("connection refused")
        return list(self.installed)

    def status(self, model):
        from jobhunt.enrich.ollama import Status

        self.status_calls += 1
        if self.state == "offline":
            return Status("offline", model)
        if not model:
            return Status("no_model")
        if model not in {m.name for m in self.installed}:
            return Status("missing", model)
        return Status(self.state, model, self.detail)


class FakeParser:
    """A parser for import tests. It recognises files holding the line `origin=<its name>` (or `origin=any`),
    whatever their type,
    and reads `key=value` lines: `id`, `source`, `title`, `company`, `url`, `description` (HTML), `warning`,
    `reject` (a Rejected with that reason) and `raise` (an error with that message). `companion_suffixes` name its
    companions: `page.html` with ("_files", ".meta") has `page_files` and `page.meta`; `discardable_suffixes` (meant
    as a subset) name the ones it marks discardable."""

    def __init__(
        self, name: str = "fake", version: str = "1", companion_suffixes: tuple[str, ...] = (),
        discardable_suffixes: tuple[str, ...] = (),
    ):
        self.name = name
        self.version = version
        self.companion_suffixes = companion_suffixes
        self.discardable_suffixes = discardable_suffixes
        self.calls = 0

    def parse(self, file):
        import re

        from jobhunt.parsers import ParsedPosting, Rejected

        self.calls += 1
        text = file.raw.decode("utf-8", errors="replace")
        fields = dict(re.findall(r"^(\w+)=(.*)$", text, re.MULTILINE))
        if fields.get("origin") not in (self.name, "any"):
            return None
        if "raise" in fields:
            raise RuntimeError(fields["raise"])
        if "reject" in fields:
            return Rejected(fields["reject"])
        source = fields.get("source", f"{self.name}.example")
        external_id = fields.get("id", "1")
        return ParsedPosting(
            source=source,
            external_id=external_id,
            url=fields.get("url", f"https://{source}/jobs/{external_id}"),
            title=fields.get("title", "Fake job"),
            company=fields.get("company", "Example Co"),
            description_html=fields.get("description", "<p>A fake posting.</p>"),
            warnings=(fields["warning"],) if "warning" in fields else (),
        )

    def companions(self, path):
        return [path.with_name(path.stem + suffix) for suffix in self.companion_suffixes]

    def discardable(self, path):
        return [path.with_name(path.stem + suffix) for suffix in self.discardable_suffixes]


def fake_file(origin: str, wrap_html: bool = False, **fields) -> str:
    """A file FakeParser(origin) recognises; `wrap_html` puts the lines in an HTML page."""
    lines = "\n".join([f"origin={origin}", *(f"{k}={v}" for k, v in fields.items())])
    return f"<html><head><title>x</title></head><body>\n{lines}\n</body></html>\n" if wrap_html else lines + "\n"
