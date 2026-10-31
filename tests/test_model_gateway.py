import json
from http.server import ThreadingHTTPServer
import threading
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import httpx

from calc.adapters import model_gateway


def send(url, *, key="local-token", stream=False):
    request = Request(url, data=json.dumps({"model": "deepseek-flash", "messages": [
        {"role": "user", "content": "Test request"}], "stream": stream}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read()


def test_gateway_auth_budget_forwarding_and_durable_usage(monkeypatch, tmp_path):
    forwarded = []

    def upstream(request):
        pending = list(tmp_path.glob("main/task-1/*.json"))
        assert len(pending) == 1
        assert json.loads(pending[0].read_text())["state"] == "started"
        forwarded.append(request)
        assert request.headers["Authorization"] == "Bearer upstream-secret"
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "enabled"}
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}],
                                        "usage": {"prompt_tokens": 11, "completion_tokens": 2,
                                                  "total_tokens": 13}})

    real_client = httpx.Client
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(upstream), **kwargs))
    gateway = model_gateway.Gateway(tmp_path, "http://upstream.test", "upstream-secret", "local-token", requests=1)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/v1/main/task-1/chat/completions"
    try:
        assert send(url, key="wrong")[0] == 401
        assert send(url)[0] == 200
        assert send(url)[0] == 429
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert len(forwarded) == 1
    records = list(tmp_path.glob("main/task-1/*.json"))
    assert len(records) == 1
    text = records[0].read_text()
    assert "upstream-secret" not in text and "local-token" not in text
    resumed = model_gateway.Gateway(tmp_path, "http://upstream.test", "another", "different", requests=1)
    assert resumed.counts["main/task-1"] == {"requests": 1, "tokens": 13, "missing_usage": 0}


def test_gateway_preserves_streaming_tool_calls_and_reads_final_usage(monkeypatch, tmp_path):
    chunks = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                       "function": {"name": "search", "arguments": '{"query":"fact"}'}}]}}]},
        {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26}},
    ]
    raw = "".join("data: " + json.dumps(item) + "\n\n" for item in chunks) + "data: [DONE]\n\n"

    def upstream(request):
        assert json.loads(request.content)["stream_options"]["include_usage"]
        return httpx.Response(200, content=raw, headers={"Content-Type": "text/event-stream"})

    real_client = httpx.Client
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(upstream), **kwargs))
    gateway = model_gateway.Gateway(tmp_path, "http://upstream.test", "upstream", "local-token")
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        status, content = send(f"http://127.0.0.1:{server.server_port}/v1/dynaflow/q1/chat/completions", stream=True)
        assert status == 200 and content.decode() == raw
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert gateway.counts["dynaflow/q1"]["tokens"] == 26


def test_gateway_resumes_pending_calls_as_unknown_not_free(tmp_path):
    path = tmp_path / "main" / "q1" / "pending.json"
    model_gateway.persist_record(path, {"task_key": "main/q1", "state": "started", "request": {}})
    resumed = model_gateway.Gateway(tmp_path, "http://upstream.test", "provider", "local")
    assert resumed.counts["main/q1"] == {"requests": 1, "tokens": 0, "missing_usage": 1}


def test_gateway_drains_usage_when_response_headers_cannot_be_delivered(monkeypatch, tmp_path):
    def upstream(request):
        return httpx.Response(200, json={"choices": [], "usage": {
            "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})

    real_client = httpx.Client
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(upstream), **kwargs))
    gateway = model_gateway.Gateway(tmp_path, "http://upstream.test", "upstream", "local-token")
    handler = gateway.handler()

    def broken_headers(self):
        raise BrokenPipeError("Disconnected before headers")

    monkeypatch.setattr(handler, "end_headers", broken_headers)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        try:
            send(f"http://127.0.0.1:{server.server_port}/v1/main/disconnect/chat/completions")
        except Exception:
            pass  # The local client receives no headers; usage must still be persisted.
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    record = json.loads(next(tmp_path.glob("main/disconnect/*.json")).read_text())
    assert record["client_disconnected"] and record["usage"]["total_tokens"] == 10
