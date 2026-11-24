#!/usr/bin/env python
"""A minimal, read-only MCP server for Corre Cortes. One tool: get_training_context.

    python mcp_server.py              # stdio (for MCP Inspector and local clients)
    python mcp_server.py --http 8765  # Streamable HTTP on http://127.0.0.1:8765/mcp

Local only. The HTTP mode binds to 127.0.0.1 and there is deliberately no option to change that;
exposing it (a tunnel, a public URL) is a separate decision that needs authentication first.
The database is opened read-only, so nothing here can change your data.

Standard library only. It speaks the small part of MCP that a tools-only server needs:
initialize, ping, tools/list and tools/call, over stdio or Streamable HTTP (JSON responses).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

os.chdir(Path(__file__).resolve().parent)

import training_context as context  # noqa: E402

SERVER_NAME = "corre-cortes"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOLS = ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]
DB_PATH = "data_hub.db"
MAX_BODY_BYTES = 64 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

# The first 512 characters matter most to the client's model.
INSTRUCTIONS = (
    "Read-only training data from the athlete's Garmin watch (Corre Cortes). Call get_training_context "
    "before recommending any workout. Check freshness.stale and the missing list first, and never invent "
    "values listed as missing: say what is unknown instead."
)

TOOL = {
    "name": "get_training_context",
    "title": "Get training context",
    "description": (
        "Use this before recommending or reviewing any run or workout. Returns the athlete's recent training from "
        "Garmin: 7, 14 and 28 day training load, weekly mileage (Monday to Sunday), the longest run of each recent "
        "week, recovery (sleep, HRV, resting heart rate, body battery, stress with 7 and 28 day trends and simple flags), "
        "strength sessions, recent activities, and when Garmin data last synced. Read-only. Always check "
        "freshness.stale and the missing list; null means unknown, not zero."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "recent_activities": {
                "type": "integer",
                "minimum": 1,
                "maximum": context.MAX_RECENT,
                "default": context.DEFAULT_RECENT,
                "description": "How many of the most recent activities to include.",
            }
        },
        "additionalProperties": False,
    },
    "outputSchema": {
        "type": "object",
        "required": ["as_of", "units", "freshness", "training_load", "weekly_mileage", "recent_long_runs",
                     "quality_sessions", "recovery", "recent_strength_sessions", "recent_activities", "missing"],
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
}


# ---------- the tool ----------

def local_now():
    """(UTC now, the Mac's current local date, a label for its time zone)."""
    now = datetime.now(timezone.utc)
    here = now.astimezone()
    label = f"{here.tzname()} (UTC{here.strftime('%z')[:3]}:{here.strftime('%z')[3:]})"
    return now, here.date(), label


def call_get_training_context(arguments):
    arguments = arguments or {}
    unknown = set(arguments) - {"recent_activities"}
    if unknown:
        raise ValueError(f"Unknown argument(s): {', '.join(sorted(unknown))}")
    limit = arguments.get("recent_activities", context.DEFAULT_RECENT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= context.MAX_RECENT:
        raise ValueError(f"recent_activities must be an integer from 1 to {context.MAX_RECENT}")
    now, today, label = local_now()
    connection = context.open_read_only(DB_PATH)
    try:
        return context.build_context(connection, now, today, context.load_status(), limit, label)
    finally:
        connection.close()


TOOLS = {"get_training_context": call_get_training_context}


# ---------- JSON-RPC / MCP ----------

def error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_message(message):
    """One JSON-RPC message in, response out. Returns None for notifications (nothing to send)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
    method, request_id, params = message["method"], message.get("id"), message.get("params") or {}
    is_notification = "id" not in message

    if is_notification:
        return None  # notifications/initialized, notifications/cancelled, ...
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[-1]
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "Corre Cortes", "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return error(request_id, -32602, f"Unknown tool: {name}")
        try:
            data = TOOLS[name](params.get("arguments"))
        except ValueError as problem:
            # Bad arguments come back as a tool error so the model can correct itself.
            return {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": str(problem)}]}}
        except Exception as problem:  # the database or status file is unavailable, for example
            print(f"tool failed: {type(problem).__name__}: {problem}", file=sys.stderr)
            return {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": "The training data is temporarily unavailable."}]}}
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": json.dumps(data, separators=(",", ":"))}],
            "structuredContent": data,
            "isError": False,
        }}
    return error(request_id, -32601, f"Method not found: {method}")


def handle_payload(payload):
    """A parsed JSON body: a single message or a batch. Returns the response body, or None."""
    if isinstance(payload, list):
        responses = [r for r in (handle_message(m) for m in payload) if r is not None]
        return responses or None
    return handle_message(payload)


# ---------- stdio ----------

def serve_stdio(stdin=sys.stdin, stdout=sys.stdout):
    """Newline-delimited JSON-RPC. Only protocol messages go to stdout; logs go to stderr."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle_payload(json.loads(line))
        except json.JSONDecodeError:
            response = error(None, -32700, "Parse error")
        if response is not None:
            stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            stdout.flush()


# ---------- Streamable HTTP (loopback only) ----------

def host_allowed(host_header):
    value = host_header or ""
    host = value.rsplit(":", 1)[0] if ":" in value and not value.endswith("]") else value
    return host in LOOPBACK_HOSTS


def origin_allowed(origin):
    """Browsers send Origin; refuse any that is not this machine (DNS-rebinding protection)."""
    if not origin:
        return True
    return (urlparse(origin).hostname or "") in LOOPBACK_HOSTS


class Handler(BaseHTTPRequestHandler):
    server_version = "corre-cortes-mcp"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # never log request bodies or headers
        print(f"{self.address_string()} {format % args}", file=sys.stderr)

    def _send(self, status, body=None, extra=None):
        data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        if status >= 400:
            # The request body may be unread; do not let leftover bytes be parsed as the next request.
            self.send_header("Connection", "close")
            self.close_connection = True
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not host_allowed(self.headers.get("Host")) or not origin_allowed(self.headers.get("Origin")):
            return self._send(403, error(None, -32600, "Forbidden origin"))
        if urlparse(self.path).path != "/mcp":
            return self._send(404, error(None, -32600, "Not found"))
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._send(413 if length > MAX_BODY_BYTES else 400, error(None, -32600, "Invalid body size"))
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, error(None, -32700, "Parse error"))
        response = handle_payload(payload)
        if response is None:
            return self._send(202)  # notification accepted, nothing to return
        self._send(200, response)

    def _method_not_allowed(self):
        self._send(405, error(None, -32600, "This server only accepts POST /mcp"), {"Allow": "POST"})

    do_GET = do_DELETE = do_PUT = _method_not_allowed


def make_http_server(port):
    # 127.0.0.1 is hard-coded on purpose: reaching this from another machine is a later, explicit step.
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--http", type=int, metavar="PORT", help="Serve Streamable HTTP on 127.0.0.1:PORT/mcp instead of stdio.")
    args = parser.parse_args()
    if args.http is not None:
        server = make_http_server(args.http)
        print(f"Corre Cortes MCP (local only): http://127.0.0.1:{server.server_address[1]}/mcp  (Ctrl+C to stop)", file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    serve_stdio()
    return 0


if __name__ == "__main__":
    sys.exit(main())
