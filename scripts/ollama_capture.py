"""Record every request an Ollama client sends, and Ollama's reply, while passing both through unchanged.

A diagnostic for MCP clients (docs/mcp.md, "Seeing what the model was sent"): it shows exactly which messages, tool
descriptions, thinking setting and options a client such as ollmcp sends, which the client's screen and jobhunt's
spans don't. Point the client's Ollama address at this proxy; it forwards to the real server.

    python scripts/ollama_capture.py --out capture.jsonl [--listen 127.0.0.1:11436] [--upstream http://127.0.0.1:11434]

Each exchange is one JSON line: method, path, status, times, the request body (parsed JSON when it is JSON) and the
response. A streamed reply (`application/x-ndjson`, as `/api/chat` and `/api/generate` stream) is kept chunk by
chunk, with the chunks put together under `assembled` (content, thinking, tool calls, and the last chunk's counts and
durations, such as `prompt_eval_count`). Both addresses must be loopback ones: the proxy is for watching a local
set-up, and must not become a way to send its traffic elsewhere. The capture holds whatever the tools returned, so
keep it out of the repository (under `data/`, which is ignored, or a scratch folder).

Standard library only; not part of the jobhunt package.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import socket
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFAULT_LISTEN = "127.0.0.1:11436"
DEFAULT_UPSTREAM = "http://127.0.0.1:11434"
# Headers that belong to one connection, not to the message: never forwarded either way.
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
              "transfer-encoding", "upgrade", "content-length", "host", "accept-encoding"}
CHUNK = 65536


def is_loopback(host: str) -> bool:
    """True for `localhost` and loopback IP addresses; no name is looked up."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def parse_listen(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"--listen must be HOST:PORT, got {text!r}")
    if not is_loopback(host):
        raise ValueError(f"--listen must be a loopback address, got {host!r}")
    return host, int(port)


def parse_upstream(text: str) -> tuple[str, int]:
    parts = urlsplit(text)
    if parts.scheme != "http" or not parts.hostname:
        raise ValueError(f"--upstream must be an http:// address, got {text!r}")
    if not is_loopback(parts.hostname):
        raise ValueError(f"--upstream must be a loopback address, got {parts.hostname!r}")
    return parts.hostname, parts.port or 80


def decoded(body: bytes, content_type: str):
    """A body as JSON when it parses, else as text; None when empty."""
    if not body:
        return None
    text = body.decode("utf-8", "replace")
    if "json" in content_type or text.lstrip()[:1] in ("{", "["):
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


def assemble(chunks: list[dict]) -> dict:
    """An NDJSON stream from /api/chat or /api/generate put together: the text, thinking and tool calls joined, and
    the counts and durations of the last chunk."""
    content, thinking, tool_calls = [], [], []
    for chunk in chunks:
        message = chunk.get("message") or {}
        content.append(message.get("content") or chunk.get("response") or "")
        thinking.append(message.get("thinking") or chunk.get("thinking") or "")
        tool_calls.extend(message.get("tool_calls") or [])
    out = {"content": "".join(content), "thinking": "".join(thinking), "tool_calls": tool_calls}
    if chunks:
        out.update({k: v for k, v in chunks[-1].items() if k not in ("message", "response", "thinking")})
    return out


class Capture:
    """The open capture file; one JSON line per exchange, written whole under a lock."""

    def __init__(self, path: str):
        self.file = open(path, "a", encoding="utf-8")  # noqa: SIM115 (kept open while serving; closed by close())
        self.lock = threading.Lock()
        self.count = 0

    def write(self, record: dict) -> None:
        with self.lock:
            self.count += 1
            record = {"seq": self.count, **record}
            self.file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.file.flush()

    def close(self) -> None:
        self.file.close()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def handler_for(upstream: tuple[str, int], capture: Capture):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):  # noqa: A002 (the base class's signature)
            pass

        def _body(self) -> bytes:
            if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                parts = []
                while True:
                    size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                    if size == 0:
                        while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                            pass
                        return b"".join(parts)
                    parts.append(self.rfile.read(size))
                    self.rfile.readline()
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))

        def _forward(self) -> None:
            started, t0 = now(), time.monotonic()
            body = self._body()
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            headers["Host"] = f"{upstream[0]}:{upstream[1]}"
            if body or self.command in ("POST", "PUT", "PATCH"):
                headers["Content-Length"] = str(len(body))
            record = {"started": started, "method": self.command, "path": self.path,
                      "request": decoded(body, self.headers.get("Content-Type", ""))}
            conn = http.client.HTTPConnection(*upstream, timeout=3600)
            try:
                conn.request(self.command, self.path, body=body or None, headers=headers)
                resp = conn.getresponse()
            except OSError as exc:
                record.update(status=502, error=f"{type(exc).__name__}: {exc}", finished=now())
                capture.write(record)
                message = b"ollama_capture: the upstream Ollama server could not be reached\n"
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
                return
            content_type = resp.getheader("Content-Type", "")
            self.send_response(resp.status, resp.reason)
            for key, value in resp.getheaders():
                if key.lower() not in HOP_BY_HOP:
                    self.send_header(key, value)
            # The record is written before the reply's last bytes go out, so a client that has its whole reply can
            # read the capture of it.
            if self.command == "HEAD":
                self.send_header("Content-Length", resp.getheader("Content-Length", "0"))
                self.end_headers()
                self._record(record, resp, content_type, b"", t0)
            elif resp.getheader("Content-Length") is not None and not resp.chunked:
                data = resp.read()
                self._record(record, resp, content_type, data, t0)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                # Streamed: pass each piece on as soon as it arrives, so the client shows tokens as before.
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                received = bytearray()
                while piece := resp.read1(CHUNK):
                    received += piece
                    self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                    self.wfile.flush()
                self._record(record, resp, content_type, bytes(received), t0)
                self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            conn.close()

        def _record(self, record: dict, resp, content_type: str, received: bytes, t0: float) -> None:
            record.update(status=resp.status, finished=now(), seconds=round(time.monotonic() - t0, 3),
                          response_type=content_type)
            if "ndjson" in content_type:
                chunks = [json.loads(line) for line in received.splitlines() if line.strip()]
                record.update(response={"chunks": chunks, "assembled": assemble(chunks)})
            else:
                record["response"] = decoded(received, content_type)
            capture.write(record)

        do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = _forward

    return Handler


def serve(listen: tuple[str, int], upstream: tuple[str, int], capture: Capture) -> ThreadingHTTPServer:
    """A started server (call `serve_forever()`, or run it in a thread); `server_address` holds the bound port."""
    server = ThreadingHTTPServer(listen, handler_for(upstream, capture))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="the capture file (JSON lines, appended to)")
    parser.add_argument("--listen", default=DEFAULT_LISTEN, help=f"loopback HOST:PORT to listen on ({DEFAULT_LISTEN})")
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM,
                        help=f"the real Ollama server, a loopback http:// address ({DEFAULT_UPSTREAM})")
    args = parser.parse_args(argv)
    try:
        listen, upstream = parse_listen(args.listen), parse_upstream(args.upstream)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    capture = Capture(args.out)
    try:
        server = serve(listen, upstream, capture)
    except OSError as exc:
        print(f"error: can't listen on {args.listen}: {exc}", file=sys.stderr)
        capture.close()
        return 2
    host, port = server.server_address[:2]
    print(f"ollama_capture: http://{host}:{port} -> http://{upstream[0]}:{upstream[1]}, writing {args.out}",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        capture.close()
        print(f"ollama_capture: {capture.count} exchanges written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    socket.setdefaulttimeout(None)
    sys.exit(main())
