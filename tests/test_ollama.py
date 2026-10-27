"""The Ollama client against a stdlib HTTP stub: request bodies, error mapping and status."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jobhunt.enrich.ollama import OllamaClient, Status
from jobhunt.enrich.pipeline import StepFailed, Unreachable

TAGS = {
    "models": [
        {"name": "gemma4:12b", "digest": "d-gemma", "size": 8_000_000_000},
        {"name": "phi4:latest", "digest": "d-phi", "size": 9_000_000_000},
        {"name": "nomic-embed-text:latest", "digest": "d-nomic", "size": 270_000_000},
    ]
}
CAPABILITIES = {
    "gemma4:12b": ["completion", "thinking", "vision"],
    "phi4:latest": ["completion"],
    "nomic-embed-text:latest": ["embedding"],
}


class Stub:
    """An Ollama look-alike on 127.0.0.1. `routes` maps a path to (status, body) or a callable(request body)."""

    def __init__(self):
        self.requests: list[tuple[str, dict | None]] = []
        self.routes = {
            "/api/version": (200, {"version": "0.32.0"}),
            "/api/tags": (200, TAGS),
            "/api/show": lambda body: (200, {"capabilities": CAPABILITIES[body["model"]]}),
            "/api/ps": (200, {"models": []}),
            "/api/chat": (200, {"message": {"role": "assistant", "content": '{"lines": []}'}}),
        }
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _answer(self, body):
                stub.requests.append((self.path, body))
                route = stub.routes.get(self.path, (404, {"error": "not found"}))
                status, payload = route(body) if callable(route) else route
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._answer(None)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self._answer(json.loads(self.rfile.read(length)))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def paths(self):
        return [path for path, _ in self.requests]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    server = Stub()
    yield server
    server.close()


def closed_port_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


SCHEMA = {"type": "object", "properties": {"lines": {"type": "array"}}, "required": ["lines"]}


# --- Requests (5.1) ---


def test_version_and_models(stub):
    client = OllamaClient(stub.url)
    assert client.version() == "0.32.0"
    models = client.models()
    assert [(m.name, m.generates_text) for m in models] == [
        ("gemma4:12b", True),
        ("phi4:latest", True),
        ("nomic-embed-text:latest", False),
    ]
    client.models()
    assert stub.paths().count("/api/show") == 3  # capabilities cached per digest
    assert ("/api/show", {"model": "phi4:latest"}) in stub.requests


def test_chat_request_body_for_thinking_model(stub):
    stub.routes["/api/chat"] = (200, {"message": {"content": '{"lines": [{"line": 1, "label": "other"}]}'}})
    model = OllamaClient(stub.url).for_model("gemma4:12b", 8192)
    assert model.chat_json("system text", "user text", SCHEMA) == {"lines": [{"line": 1, "label": "other"}]}
    path, body = stub.requests[-1]
    assert path == "/api/chat"
    assert body == {
        "model": "gemma4:12b",
        "messages": [{"role": "system", "content": "system text"}, {"role": "user", "content": "user text"}],
        "stream": False,
        "format": SCHEMA,
        "keep_alive": "10m",
        "options": {"temperature": 0, "seed": 7, "num_ctx": 8192},
        "think": False,
    }


def test_think_only_sent_to_thinking_models(stub):
    model = OllamaClient(stub.url).for_model("phi4:latest", 4096)
    model.chat_json("s", "u", SCHEMA)
    body = stub.requests[-1][1]
    assert "think" not in body and body["options"]["num_ctx"] == 4096


def test_connection_refused_is_unreachable():
    client = OllamaClient(closed_port_url())
    with pytest.raises(Unreachable):
        client.version()
    from jobhunt.enrich.ollama import ChatModel

    with pytest.raises(Unreachable):
        ChatModel(client, "phi4:latest", 8192, False).chat_json("s", "u", SCHEMA)


def test_http_error_is_step_failed(stub):
    stub.routes["/api/chat"] = (500, {"error": "model runner crashed"})
    with pytest.raises(StepFailed) as err:
        OllamaClient(stub.url).for_model("phi4:latest", 8192).chat_json("s", "u", SCHEMA)
    assert "HTTP 500" in err.value.message and "model runner crashed" in err.value.message
    assert err.value.step is None


@pytest.mark.parametrize("content", ["not json", "[1, 2]", None])
def test_malformed_answer_is_step_failed(stub, content):
    stub.routes["/api/chat"] = (200, {"message": {"content": content}})
    with pytest.raises(StepFailed):
        OllamaClient(stub.url).for_model("phi4:latest", 8192).chat_json("s", "u", SCHEMA)


def test_body_not_json_is_step_failed(stub):
    stub.routes["/api/chat"] = (200, b"<html>proxy error</html>")
    with pytest.raises(StepFailed):
        OllamaClient(stub.url).for_model("phi4:latest", 8192).chat_json("s", "u", SCHEMA)


def test_slow_chat_is_step_failed_and_slow_status_is_unreachable(stub):
    def slow(body):
        time.sleep(0.5)
        return 200, {"version": "0.32.0", "message": {"content": "{}"}}

    stub.routes["/api/chat"] = slow
    stub.routes["/api/version"] = slow
    client = OllamaClient(stub.url, short_timeout=0.1, chat_timeout=0.1)
    from jobhunt.enrich.ollama import ChatModel

    with pytest.raises(StepFailed, match="did not answer"):
        ChatModel(client, "phi4:latest", 8192, False).chat_json("s", "u", SCHEMA)
    with pytest.raises(Unreachable):
        client.version()


# --- Status (5.2) ---


def test_status_offline():
    assert OllamaClient(closed_port_url()).status("gemma4:12b").state == "offline"


def test_status_states(stub):
    client = OllamaClient(stub.url)
    assert client.status(None) == Status("no_model")
    assert client.status("llama3:70b") == Status("missing", "llama3:70b")
    assert client.status("gemma4:12b") == Status("online", "gemma4:12b")
    assert client.status("gemma4:12b").ready and not client.status("llama3:70b").ready


def test_status_spill(stub):
    stub.routes["/api/ps"] = (200, {"models": [{"name": "phi4:latest", "size": 10_000, "size_vram": 7_500}]})
    status = OllamaClient(stub.url).status("phi4:latest")
    assert status.state == "spill" and status.ready and status.detail == "75% on the GPU"


def test_status_fully_on_gpu(stub):
    stub.routes["/api/ps"] = (200, {"models": [{"name": "phi4:latest", "size": 10_000, "size_vram": 10_000}]})
    assert OllamaClient(stub.url).status("phi4:latest").state == "online"


def test_status_cached_for_five_seconds(stub):
    now = [100.0]
    client = OllamaClient(stub.url, clock=lambda: now[0])
    client.status("gemma4:12b")
    calls = len(stub.requests)
    now[0] += 4.9
    client.status("gemma4:12b")
    assert len(stub.requests) == calls
    now[0] += 0.2
    client.status("gemma4:12b")
    assert len(stub.requests) > calls


# --- Embeddings ---


def embed_route(body):
    return 200, {"model": body["model"], "embeddings": [[float(len(t)), 1.0] for t in body["input"]]}


def test_embed_sends_only_model_and_texts(stub):
    stub.routes["/api/embed"] = embed_route
    vectors = OllamaClient(stub.url).embed("nomic-embed-text:latest", ["clustering: Python", "clustering: SQL"])
    assert vectors == [[18.0, 1.0], [15.0, 1.0]]
    [(path, body)] = stub.requests
    assert path == "/api/embed" and body == {
        "model": "nomic-embed-text:latest",
        "input": ["clustering: Python", "clustering: SQL"],
    }


def test_embed_batches(stub, monkeypatch):
    from jobhunt.enrich import ollama

    monkeypatch.setattr(ollama, "EMBED_BATCH", 8)
    stub.routes["/api/embed"] = embed_route
    vectors = OllamaClient(stub.url).embed("nomic-embed-text:latest", [f"skill {i}" for i in range(20)])
    assert len(vectors) == 20
    assert [len(body["input"]) for _, body in stub.requests] == [8, 8, 4]


def test_short_embedding_response(stub):
    stub.routes["/api/embed"] = lambda body: (200, {"embeddings": [[1.0]] * (len(body["input"]) - 1)})
    with pytest.raises(StepFailed, match="for 20 embeddings and got 19"):
        OllamaClient(stub.url).embed("nomic-embed-text:latest", [f"skill {i}" for i in range(20)])


def test_embed_unreachable():
    with pytest.raises(Unreachable):
        OllamaClient(closed_port_url()).embed("nomic-embed-text:latest", ["Python"])


def test_fake_embeddings_make_similar_names_similar():
    from .fakes import FakeOllama

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))

    llm, lll, sf = FakeOllama().embed("nomic-embed-text:latest", ["LLMs", "LLM", "Salesforce"])
    assert cosine(llm, lll) > 0.6 > cosine(llm, sf)
