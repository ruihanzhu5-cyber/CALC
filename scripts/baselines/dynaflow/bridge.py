"""DynaFlow /execute RPC -> common BCP BM25 /retrieve and /document.

Standard library only. No model calls, answer files or model summarization.
Run beside DynaFlow Python, outside its networkless Node container.
"""
import hmac
import json
import os
import threading
from argparse import ArgumentParser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

TOOLS = [
    {"type": "function", "function": {
        "name": "search", "description": "Search the fixed BrowseComp-Plus corpus with BM25. Returns document IDs, titles and snippets. Read documents using get_document.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 20000}}, "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_document", "description": "Read an original corpus document by docid from search. The common service truncates at 8192 tokens without model summarization.",
        "parameters": {"type": "object", "properties": {"docid": {"type": "string", "minLength": 1, "maxLength": 1000}}, "required": ["docid"], "additionalProperties": False}}},
]


class ToolBridge:
    def __init__(self, upstream="http://127.0.0.1:8765", log_path=None, token=None, timeout=120):
        parsed = urlsplit(upstream)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("upstream must be a credential-free HTTP(S) URL")
        self.upstream, self.token, self.timeout = upstream.rstrip("/"), token, timeout
        self.http = build_opener(ProxyHandler({}))
        self.log_path = Path(log_path) if log_path else None
        self.lock = threading.Lock()
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def upstream_json(self, route, payload=None):
        request = Request(self.upstream + route,
                          data=json.dumps(payload).encode("utf-8") if payload is not None else None,
                          headers={"Content-Type": "application/json"})
        with self.http.open(request, timeout=self.timeout) as response:
            return json.load(response)

    def execute(self, request):
        if not isinstance(request, dict):
            raise TypeError("request must be an object")
        name, arguments = request.get("name"), request.get("arguments")
        specs = {"search": ("/retrieve", "query", 20000), "get_document": ("/document", "docid", 1000)}
        if name not in specs:
            raise ValueError("unknown tool")
        route, field, cap = specs[name]
        if not isinstance(arguments, dict) or set(arguments) != {field}:
            raise ValueError("tool arguments do not match schema")
        value = arguments[field]
        if not isinstance(value, str) or not value.strip() or len(value) > cap:
            raise ValueError("invalid tool argument")
        return self.upstream_json(route, {field: value})

    def audit(self, request, result):
        if self.log_path:
            record = {"at": datetime.now(UTC).isoformat(), "request": request, "result": result}
            with self.lock, self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def server(self, host="127.0.0.1", port=8766):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, status, value):
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    return self.reply(200, {"status": "ok", "tools": ["search", "get_document"],
                                            "upstream_url": bridge.upstream, "upstream_check": "not_requested"})
                if self.path != "/ready":
                    return self.reply(404, {"error": "not found"})
                try:
                    self.reply(200, {"status": "ok", "tools": ["search", "get_document"], "upstream": bridge.upstream_json("/health")})
                except (OSError, ValueError) as error:
                    self.reply(503, {"status": "upstream_unavailable", "error_type": type(error).__name__})

            def do_POST(self):
                if self.path != "/execute":
                    return self.reply(404, {"error": "not found"})
                if bridge.token and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bridge.token):
                    return self.reply(401, {"error": "unauthorized"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1000000:
                        raise ValueError("invalid request size")
                    request = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError):
                    return self.reply(400, {"error": "invalid JSON request"})
                try:
                    result = bridge.execute(request)
                except HTTPError as error:
                    result = {"is_error": True, "error": "BCP service HTTP " + str(error.code)}
                except (ValueError, TypeError) as error:
                    result = {"is_error": True, "error": str(error)}
                except OSError as error:
                    result = {"is_error": True, "error_type": type(error).__name__}
                bridge.audit(request, result)
                self.reply(200, result)

        return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", default="http://127.0.0.1:8765")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--token-env", default="DYNAFLOW_TOOL_API_KEY")
    args = parser.parse_args()
    server = ToolBridge(args.upstream, args.log, os.environ.get(args.token_env)).server(port=args.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
