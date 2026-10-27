"""HTTP client for a local Ollama server (stdlib urllib). Implements the LLM protocol; no database.

The address is fixed when the command starts; nothing from the browser can change it.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .pipeline import StepFailed, Unreachable

DEFAULT_URL = "http://localhost:11434"
SHORT_TIMEOUT = 1.5  # metadata and status calls, so an unreachable server never holds up a page
CHAT_TIMEOUT = 600
STATUS_TTL = 5
KEEP_ALIVE = "10m"
SEED = 7
EMBED_BATCH = 64  # texts per /api/embed request


@dataclass(frozen=True)
class ModelInfo:
    name: str
    digest: str
    size: int
    capabilities: tuple[str, ...]

    @property
    def generates_text(self) -> bool:
        return "completion" in self.capabilities

    @property
    def embeds(self) -> bool:
        return "embedding" in self.capabilities


@dataclass(frozen=True)
class Status:
    state: str  # 'offline', 'no_model', 'missing', 'online' or 'spill'
    model: str | None = None
    detail: str | None = None

    @property
    def ready(self) -> bool:
        """Model actions can run: the server is up and the selected model is installed."""
        return self.state in ("online", "spill")


class OllamaClient:
    def __init__(
        self, url: str = DEFAULT_URL, clock=time.monotonic, short_timeout=SHORT_TIMEOUT, chat_timeout=CHAT_TIMEOUT
    ):
        self.url = url.rstrip("/")
        self.short_timeout = short_timeout
        self.chat_timeout = chat_timeout
        self._clock = clock
        self._capabilities: dict[str, tuple[str, ...]] = {}  # by model digest
        self._status: dict[str | None, tuple[float, Status]] = {}
        self._lock = threading.Lock()

    def _request(self, path: str, body: dict | None = None, chat: bool = False) -> dict:
        timeout = self.chat_timeout if chat else self.short_timeout
        request = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise StepFailed(None, f"Ollama returned HTTP {exc.code}: {detail}") from None
        except TimeoutError:
            # Connected, then no answer in time: for a chat that is the request's failure, not the server's.
            if chat:
                raise StepFailed(None, f"Ollama did not answer within {timeout:g} s") from None
            raise Unreachable(f"no answer from {self.url}") from None
        except OSError as exc:  # URLError and connection errors
            raise Unreachable(f"cannot reach {self.url}: {getattr(exc, 'reason', exc)}") from None
        try:
            return json.loads(raw)
        except ValueError:
            raise StepFailed(None, "Ollama returned a body that is not JSON") from None

    def version(self) -> str:
        return self._request("/api/version")["version"]

    def capabilities(self, name: str, digest: str) -> tuple[str, ...]:
        if digest not in self._capabilities:
            shown = self._request("/api/show", {"model": name})
            # Servers older than the capabilities field only had text models.
            self._capabilities[digest] = tuple(shown.get("capabilities") or ("completion",))
        return self._capabilities[digest]

    def models(self) -> list[ModelInfo]:
        """Installed models, with capabilities from /api/show (cached per digest)."""
        tags = self._request("/api/tags").get("models", [])
        return [
            ModelInfo(
                m["name"], m.get("digest", ""), m.get("size", 0), self.capabilities(m["name"], m.get("digest", ""))
            )
            for m in tags
        ]

    def loaded(self) -> list[dict]:
        return self._request("/api/ps").get("models", [])

    def status(self, model: str | None) -> Status:
        """Offline, no model, missing, online or spill; cached for STATUS_TTL seconds per model."""
        now = self._clock()
        with self._lock:
            cached = self._status.get(model)
            if cached and now - cached[0] < STATUS_TTL:
                return cached[1]
        status = self._fetch_status(model)
        with self._lock:
            self._status[model] = (now, status)
        return status

    def _fetch_status(self, model: str | None) -> Status:
        try:
            self.version()
            if not model:
                return Status("no_model")
            if model not in {m.name for m in self.models()}:
                return Status("missing", model)
            for running in self.loaded():
                if running.get("name") == model and running.get("size_vram", 0) < running.get("size", 0):
                    share = running["size_vram"] / running["size"] if running["size"] else 0
                    return Status("spill", model, f"{share:.0%} on the GPU")
            return Status("online", model)
        except (Unreachable, StepFailed, KeyError) as exc:
            return Status("offline", model, str(exc))

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """One vector per text, from /api/embed in batches. Only the model and the texts are sent (embeddings
        have no sampling options). A batch answered with the wrong number of vectors fails the whole call."""
        vectors: list[list[float]] = []
        for at in range(0, len(texts), EMBED_BATCH):
            batch = texts[at:at + EMBED_BATCH]
            response = self._request("/api/embed", {"model": model, "input": batch}, chat=True)
            got = response.get("embeddings")
            if not isinstance(got, list) or len(got) != len(batch):
                count = len(got) if isinstance(got, list) else 0
                raise StepFailed("embed", f"asked {model} for {len(batch)} embeddings and got {count}")
            vectors.extend(got)
        return vectors

    def for_model(self, model: str, num_ctx: int) -> ChatModel:
        thinking = False
        for info in self.models():
            if info.name == model:
                thinking = "thinking" in info.capabilities
        return ChatModel(self, model, num_ctx, thinking)


class ChatModel:
    """One model with fixed request options; what the pipeline steps call."""

    def __init__(self, client: OllamaClient, model: str, num_ctx: int, thinking: bool):
        self.client = client
        self.model = model
        self.num_ctx = num_ctx
        self.thinking = thinking

    def request_body(self, system: str, user: str, schema: dict) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": schema,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "seed": SEED, "num_ctx": self.num_ctx},
        }
        if self.thinking:
            body["think"] = False
        return body

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        response = self.client._request("/api/chat", self.request_body(system, user, schema), chat=True)
        try:
            parsed = json.loads(response["message"]["content"])
        except (KeyError, TypeError, ValueError):
            raise StepFailed(None, "the model's answer is not valid JSON") from None
        if not isinstance(parsed, dict):
            raise StepFailed(None, "the model's answer is not a JSON object")
        return parsed
