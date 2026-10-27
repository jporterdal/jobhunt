"""Request checks that stand in for authentication on a local, single-user app (design D6).

- Every request must carry a Host header naming the interface itself, which defeats DNS rebinding.
- Every request that can change data must come from a page of the interface: its Origin (or, when
  that is missing, its Referer) must match. Requests with neither header are refused.
"""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

from flask import Flask, abort, request

LOOPBACK = ("127.0.0.1", "localhost", "::1")
WILDCARD = ("0.0.0.0", "::", "")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _host_header(name: str, port: int) -> str:
    name = f"[{name}]" if ":" in name else name
    return name if port == 80 else f"{name}:{port}"


def allowed_hosts(host: str, port: int) -> set[str]:
    """Host header values the interface answers to when serving on host:port."""
    names = set(LOOPBACK)
    if host in WILDCARD:
        # Bound to every interface: also accept this machine's own name and addresses.
        hostname = socket.gethostname()
        names.add(hostname)
        try:
            names.update(socket.gethostbyname_ex(hostname)[2])
        except OSError:
            pass
    else:
        names.add(host)
    return {_host_header(name.lower(), port) for name in names}


def _origin_of(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else None


def install(app: Flask, hosts: set[str]) -> None:
    origins = {f"http://{h}" for h in hosts}

    @app.before_request
    def check_request():
        if request.host.lower() not in hosts:
            abort(403)
        if request.method in SAFE_METHODS:
            return
        origin = request.headers.get("Origin")
        if not origin:
            referer = request.headers.get("Referer")
            origin = _origin_of(referer) if referer else None
        if not origin or origin.lower() not in origins:
            abort(403)
