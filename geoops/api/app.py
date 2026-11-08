"""Minimal HTTP API over the domain registry.

Two real endpoints are exposed:

    GET /api/v1/health
    GET /api/v1/objects/<object_id>
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse


def create_server(
    registry: Any,
    extra: Optional[Dict[str, Any]] = None,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    extra_data = dict(extra or {})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/v1/health":
                self._json(
                    200,
                    {
                        "status": "ok",
                        "objects": len(registry),
                        "context": extra_data,
                    },
                )
                return
            prefix = "/api/v1/objects/"
            if path.startswith(prefix):
                object_id = unquote(path[len(prefix):])
                obj = registry.get(object_id)
                if obj is None:
                    self._json(
                        404, {"error": "object not found", "object_id": object_id}
                    )
                else:
                    self._json(200, obj.to_dict())
                return
            self._json(404, {"error": "unknown endpoint", "path": path})

        def _json(self, code: int, payload: Dict[str, Any]):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return ThreadingHTTPServer((host, port), Handler)
