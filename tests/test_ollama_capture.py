"""scripts/ollama_capture.py against a stub Ollama on loopback: replies pass through unchanged (streamed ones chunk by
chunk), each exchange is one JSON line with the request and the assembled stream, and only loopback addresses are
accepted. No model, no network beyond 127.0.0.1."""

import http.client
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ollama_capture.py"
spec = importlib.util.spec_from_file_location("ollama_capture", SCRIPT)
capture_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture_mod)

STREAM = [
    {"model": "m", "message": {"role": "assistant", "content": "", "thinking": "Search "}, "done": False},
    {"model": "m", "message": {"role": "assistant", "content": "", "thinking": "first."}, "done": False},
    {"model": "m", "message": {"role": "assistant", "content": "",
                               "tool_calls": [{"function": {"name": "jobhunt_search_postings",
                                                            "arguments": {"q": "Analyst"}}}]}, "done": False},
    {"model": "m", "message": {"role": "assistant", "content": "Done"}, "done": True, "done_reason": "stop",
     "prompt_eval_count": 1234, "eval_count": 56},
]
TAGS = {"models": [{"name": "m"}]}


class Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen: list = []

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        body = json.dumps(TAGS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        Stub.seen.append((self.path, self.headers.get("Host"), self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for chunk in STREAM:
            line = json.dumps(chunk).encode() + b"\n"
            self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")


def started(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def proxy(tmp_path):
    Stub.seen = []
    upstream = started(ThreadingHTTPServer(("127.0.0.1", 0), Stub))
    out = tmp_path / "capture.jsonl"
    capture = capture_mod.Capture(str(out))
    server = started(capture_mod.serve(("127.0.0.1", 0), upstream.server_address[:2], capture))
    yield server.server_address[1], out, upstream.server_address[1]
    server.shutdown()
    server.server_close()
    upstream.shutdown()
    upstream.server_close()
    capture.close()


def request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def records(out):
    return [json.loads(line) for line in out.read_text().splitlines()]


def test_a_streamed_chat_passes_through_and_is_recorded(proxy):
    port, out, upstream_port = proxy
    body = {"model": "m", "messages": [{"role": "user", "content": "Which postings are remote?"}],
            "tools": [{"type": "function", "function": {"name": "jobhunt_search_postings", "description": "Search"}}],
            "think": True, "stream": True}
    resp, data = request(port, "POST", "/api/chat", body)
    assert resp.status == 200 and resp.getheader("Content-Type") == "application/x-ndjson"
    assert [json.loads(line) for line in data.splitlines()] == STREAM
    path, host, sent = Stub.seen[0]
    assert path == "/api/chat" and json.loads(sent) == body and host == f"127.0.0.1:{upstream_port}"
    [record] = records(out)
    assert record["seq"] == 1 and record["method"] == "POST" and record["path"] == "/api/chat"
    assert record["status"] == 200 and record["request"] == body
    assert record["response"]["chunks"] == STREAM
    assembled = record["response"]["assembled"]
    assert assembled["thinking"] == "Search first." and assembled["content"] == "Done"
    assert assembled["tool_calls"] == STREAM[2]["message"]["tool_calls"]
    assert (assembled["prompt_eval_count"], assembled["eval_count"], assembled["done_reason"]) == (1234, 56, "stop")


def test_plain_replies_and_head_requests(proxy):
    port, out, _ = proxy
    resp, data = request(port, "GET", "/api/tags")
    assert resp.status == 200 and json.loads(data) == TAGS
    resp, data = request(port, "HEAD", "/")
    assert resp.status == 200 and data == b""
    first, second = records(out)
    assert (first["path"], first["response"], first["request"]) == ("/api/tags", TAGS, None)
    assert (second["method"], second["seq"]) == ("HEAD", 2)


def test_an_unreachable_upstream_is_a_502_and_recorded(tmp_path):
    out = tmp_path / "capture.jsonl"
    capture = capture_mod.Capture(str(out))
    closed = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    dead_port = closed.server_address[1]
    closed.server_close()
    server = started(capture_mod.serve(("127.0.0.1", 0), ("127.0.0.1", dead_port), capture))
    try:
        resp, data = request(server.server_address[1], "POST", "/api/chat", {"model": "m"})
    finally:
        server.shutdown()
        server.server_close()
        capture.close()
    assert resp.status == 502 and b"could not be reached" in data
    [record] = records(out)
    assert record["status"] == 502 and record["request"] == {"model": "m"} and "error" in record


@pytest.mark.parametrize("argv, named", [
    (["--listen", "0.0.0.0:11436"], "loopback"),
    (["--listen", "192.168.1.5:11436"], "loopback"),
    (["--upstream", "http://example.com:11434"], "loopback"),
    (["--upstream", "https://127.0.0.1:11434"], "http://"),
    (["--listen", "11436"], "HOST:PORT"),
])
def test_only_loopback_addresses_are_accepted(tmp_path, capsys, argv, named):
    out = tmp_path / "capture.jsonl"
    assert capture_mod.main(["--out", str(out), *argv]) == 2
    assert named in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("host, loopback", [
    ("localhost", True), ("127.0.0.1", True), ("127.5.6.7", True), ("::1", True), ("[::1]", True),
    ("0.0.0.0", False), ("10.0.0.1", False), ("ollama.example.com", False),
])
def test_is_loopback(host, loopback):
    assert capture_mod.is_loopback(host) is loopback
