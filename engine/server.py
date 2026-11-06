"""Stdlib HTTP daemon and SSE event stream for NecroKernel-OS hypervisor."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from .hypervisor import Hypervisor
from .mcp_gateway import MCP_TOOLS_SPEC, dispatch_tool_call, get_or_create_worker, handle_json_rpc

# Shared hypervisor instance
HYPERVISOR = Hypervisor(in_process=True)
ACTIVE_SSE_STREAMS = 0
MAX_SSE_STREAMS = 16
SSE_LOCK = threading.Lock()

ALLOWED_ORIGINS = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}


class NecroHttpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Credentials", "true")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def _validate_request(self) -> bool:
        """Validate host, content-type and origin security requirements."""
        host = self.headers.get("Host", "").split(":")[0]
        if host not in ("localhost", "127.0.0.1", "0.0.0.0", "testserver"):
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden host")
            return False

        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden origin")
            return False

        if self.command == "POST":
            ctype = self.headers.get("Content-Type", "").split(";")[0].strip()
            if ctype != "application/json":
                self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")
                return False

        return True

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        clen = self.headers.get("Content-Length")
        if not clen:
            return {}
        try:
            raw = self.rfile.read(int(clen))
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return None

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._validate_request():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            self._send_json(HTTPStatus.OK, {
                "status": "ok",
                "supervisor_pid": os.getpid(),
                "worker_pid": HYPERVISOR.worker_pid,
                "hv_state": HYPERVISOR.state,
            })
        elif path == "/tools":
            self._send_json(HTTPStatus.OK, {"tools": MCP_TOOLS_SPEC})
        elif path == "/hv/state":
            self._send_json(HTTPStatus.OK, {
                "state": HYPERVISOR.state,
                "worker_pid": HYPERVISOR.worker_pid,
                "quarantined": HYPERVISOR.worker.quarantined,
                "reanimations": HYPERVISOR.worker.reanimation_count,
            })
        elif path.startswith("/workers/"):
            parts = path.strip("/").split("/")
            if len(parts) == 2:
                w_name = parts[1]
                w = get_or_create_worker(w_name)
                self._send_json(HTTPStatus.OK, {
                    "worker": w.name,
                    "pid": w.pid,
                    "quarantined": w.quarantined,
                    "has_crash_dump": (w.latest_crash_dump is not None),
                })
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/events":
            self._handle_sse(query)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._validate_request():
            return

        body = self._read_json_body()
        if body is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "Malformed JSON")
            return

        path = urllib.parse.urlparse(self.path).path

        if path == "/hv/crash":
            kind = body.get("kind")
            res = HYPERVISOR.crash(kind)
            code = res.get("code", HTTPStatus.OK)
            self._send_json(code, res)
        elif path == "/hv/reanimate":
            res = HYPERVISOR.reanimate()
            code = res.get("code", HTTPStatus.OK)
            self._send_json(code, res)
        elif path == "/hv/reset":
            res = HYPERVISOR.reset()
            self._send_json(HTTPStatus.OK, res)
        elif path == "/rpc":
            resp = handle_json_rpc(body)
            self._send_json(HTTPStatus.OK, resp)
        elif path.startswith("/workers/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                w_name = parts[1]
                action = parts[2]
                w = get_or_create_worker(w_name)
                if action == "crash":
                    kind = body.get("kind")
                    try:
                        w.inject_fault(kind)
                    except Exception:
                        pass
                    dump = w.latest_crash_dump
                    self._send_json(HTTPStatus.OK, {"status": "crashed", "dump": dump.to_dict() if dump else None})
                elif action == "reset":
                    w.reset()
                    self._send_json(HTTPStatus.OK, {"status": "reset", "worker": w.name, "pid": w.pid})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_sse(self, query: Dict[str, Any]) -> None:
        global ACTIVE_SSE_STREAMS
        with SSE_LOCK:
            if ACTIVE_SSE_STREAMS >= MAX_SSE_STREAMS:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Too many active event streams (max 16)")
                return
            ACTIVE_SSE_STREAMS += 1

        # Check limit/after query parameters
        after_id = 0
        limit = 100
        try:
            if "after" in query:
                after_id = int(query["after"][0])
            if "limit" in query:
                limit = int(query["limit"][0])
        except ValueError:
            with SSE_LOCK:
                ACTIVE_SSE_STREAMS -= 1
            self.send_error(HTTPStatus.BAD_REQUEST, "after/limit must be integers")
            return

        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        sub_queue = HYPERVISOR.bus.subscribe()
        try:
            # Send initial backlog
            history = HYPERVISOR.bus.get_history(limit=limit, after_id=after_id)
            for ev in history:
                chunk = f"event: {ev['type']}\nid: {ev['id']}\ndata: {json.dumps(ev)}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

            # Stream live events
            while True:
                try:
                    ev = sub_queue.get(timeout=1.0)
                    chunk = f"event: {ev['type']}\nid: {ev['id']}\ndata: {json.dumps(ev)}\n\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    # Keep-alive comment pulse
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            HYPERVISOR.bus.unsubscribe(sub_queue)
            with SSE_LOCK:
                ACTIVE_SSE_STREAMS -= 1


def run_server(host: Optional[str] = None, port: Optional[int] = None) -> None:
    host = host or os.environ.get("NECRO_HOST", "127.0.0.1")
    port = port or int(os.environ.get("NECRO_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), NecroHttpHandler)
    print(f"NecroKernel-OS Hypervisor Engine running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    run_server()
