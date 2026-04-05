"""
Lightweight metrics server.

Exposes a plain-text /metrics endpoint (Prometheus-compatible) on a
background thread.  No external dependencies required — uses only stdlib.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict


# ---------------------------------------------------------------------------
# In-process metrics registry
# ---------------------------------------------------------------------------

class _Registry:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}

    def inc(self, name: str, value: float = 1.0, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def set(self, name: str, value: float, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def get(self, name: str, labels: dict | None = None) -> float:
        key = self._key(name, labels)
        with self._lock:
            return self._gauges.get(key, self._counters.get(key, 0.0))

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for k, v in sorted(self._counters.items()):
                lines.append(f"{k} {v}")
            for k, v in sorted(self._gauges.items()):
                lines.append(f"{k} {v}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _key(name: str, labels: dict | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Module-level singleton — import and use directly
metrics = _Registry()


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    registry: _Registry

    def do_GET(self):
        if self.path in ("/metrics", "/"):
            body = self.registry.render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # silence default access log


class MetricsServer:
    def __init__(self, port: int = 8000):
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler = type(
            "_BoundHandler",
            (_Handler,),
            {"registry": metrics},
        )
        self._server = HTTPServer(("", self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="metrics-server",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
