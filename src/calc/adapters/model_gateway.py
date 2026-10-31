"""Authenticated local API gateway for shared concurrency, budgets and usage logs.

Each client uses /v1/<run-id>/<task-id> as its API base URL. Requests and
provider responses are recorded, but authentication headers never are.
"""

from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
from time import perf_counter, time
from typing import Any
from uuid import uuid4

import httpx


def persist_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def response_usage(raw: bytes, streaming: bool) -> dict[str, Any]:
    if not streaming:
        try:
            return json.loads(raw).get("usage") or {}
        except (ValueError, AttributeError):
            return {}
    usage: dict[str, Any] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
            continue
        try:
            event = json.loads(line[5:])
            usage = event.get("usage") or usage
        except (ValueError, AttributeError):
            continue
    return usage


class Gateway:
    def __init__(self, root: Path, upstream: str, api_key: str, local_key: str,
                 *, requests: int = 100, tokens: int = 160000) -> None:
        self.root, self.upstream = root, upstream.rstrip("/")
        self.api_key, self.local_key = api_key, local_key
        self.request_limit, self.token_limit = requests, tokens
        self.lock = threading.Lock()
        self.counts: dict[str, dict[str, int]] = {}
        self.root.mkdir(parents=True, exist_ok=True)
        # Resume accounting from durable records after a service restart.
        for path in sorted(self.root.glob("*/*/*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            self.account(record["task_key"], record.get("usage") or {})

    def account(self, key: str, usage: dict[str, Any]) -> None:
        total = usage.get("total_tokens")
        if total is None:
            total = int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
        item = self.counts.setdefault(key, {"requests": 0, "tokens": 0, "missing_usage": 0})
        item["requests"] += 1
        item["tokens"] += int(total)
        item["missing_usage"] += int(not bool(usage))

    def handler(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, status: int, data: dict) -> None:
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health":
                    self.reply(200, {"status": "ok", "max_in_flight_model_requests": 1,
                                     "request_limit_per_task": gateway.request_limit,
                                     "observed_token_stop_threshold": gateway.token_limit})
                else:
                    self.reply(404, {"error": {"message": "Unknown route"}})

            def do_POST(self):
                expected = f"Bearer {gateway.local_key}"
                if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
                    self.reply(401, {"error": {"message": "Local gateway authentication failed"}})
                    return
                match = re.fullmatch(r"/v1/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/chat/completions", self.path)
                if not match:
                    self.reply(400, {"error": {"message": "Use /v1/<run-id>/<task-id> as API base"}})
                    return
                run_id, task_id = match.groups()
                task_key = f"{run_id}/{task_id}"
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                    if body.get("model") not in {"deepseek-flash", "deepseek-v4-flash"}:
                        raise ValueError("Unexpected backbone")
                except (ValueError, AttributeError):
                    self.reply(400, {"error": {"message": "Invalid model request"}})
                    return
                body["model"] = "deepseek-flash"
                body["thinking"] = {"type": "enabled"}
                body["reasoning_effort"] = "high"
                body.pop("temperature", None)  # Ignored by the provider in thinking mode.
                body["max_tokens"] = min(int(body.pop("max_completion_tokens", body.get("max_tokens", 4096))), 4096)
                streaming = bool(body.get("stream", False))
                if streaming:
                    body["stream_options"] = {**(body.get("stream_options") or {}), "include_usage": True}
                queued = perf_counter()
                with gateway.lock:
                    previous = gateway.counts.get(task_key, {"requests": 0, "tokens": 0, "missing_usage": 0})
                    if previous["missing_usage"]:
                        self.reply(409, {"error": {"type": "accounting_incomplete",
                                                  "message": "An earlier submitted request has unknown usage"}})
                        return
                    if previous["requests"] >= gateway.request_limit or previous["tokens"] >= gateway.token_limit:
                        self.reply(429, {"error": {"type": "task_budget_exhausted",
                                                  "message": "Shared task budget exhausted"}})
                        return
                    record = {"task_key": task_key, "started_unix": time(), "state": "started",
                              "queue_seconds": perf_counter() - queued, "request": body}
                    record_path = gateway.root / run_id / task_id / f"{uuid4().hex}.json"
                    # Persist and reserve before submitting any potentially billable request.
                    persist_record(record_path, record)
                    gateway.account(task_key, {})
                    started = perf_counter()
                    raw = bytearray()
                    connected = True
                    try:
                        with httpx.Client(timeout=300) as client:
                            with client.stream("POST", f"{gateway.upstream}/chat/completions", json=body,
                                               headers={"Authorization": f"Bearer {gateway.api_key}"}) as response:
                                record["http_status"] = response.status_code
                                try:
                                    self.send_response(response.status_code)
                                    self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
                                    self.send_header("Connection", "close")
                                    self.end_headers()
                                except OSError:
                                    # A client can time out while queued. Still drain the provider
                                    # response so its billable usage is not discarded.
                                    connected = False
                                for chunk in response.iter_bytes():
                                    raw.extend(chunk)
                                    if connected:
                                        try:
                                            self.wfile.write(chunk)
                                            self.wfile.flush()
                                        except OSError:
                                            connected = False
                    except httpx.HTTPError as exc:
                        record["error_type"] = type(exc).__name__
                        if not raw and "http_status" not in record:
                            try:
                                self.reply(502, {"error": {"message": "Upstream transport error"}})
                            except OSError:
                                connected = False
                    finally:
                        record["elapsed_seconds"] = perf_counter() - started
                        record["client_disconnected"] = not connected
                        record["response"] = bytes(raw).decode("utf-8", errors="replace")
                        record["usage"] = response_usage(bytes(raw), streaming)
                        record["state"] = "finished"
                        # Replace the in-flight reservation without double-counting the request.
                        item = gateway.counts[task_key]
                        item["requests"] -= 1
                        item["missing_usage"] -= 1
                        gateway.account(task_key, record["usage"])
                        persist_record(record_path, record)

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    gateway = Gateway(args.log_dir, os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                      os.environ["DEEPSEEK_API_KEY"], os.environ["CALC_GATEWAY_KEY"])
    ThreadingHTTPServer((args.host, args.port), gateway.handler()).serve_forever()


if __name__ == "__main__":
    main()
