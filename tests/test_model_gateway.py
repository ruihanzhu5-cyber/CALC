import json
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import threading
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import httpx
import pytest

from calc.adapters import model_gateway


def send(url, *, key="local-token", stream=False, extra=None):
    request = Request(url, data=json.dumps({"model": "deepseek-flash", "messages": [
        {"role": "user", "content": "Test request"}], "stream": stream, **(extra or {})}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read()


@pytest.mark.parametrize("output_tokens", [4096, 16384])
def test_gateway_auth_budget_forwarding_and_durable_usage(monkeypatch, tmp_path, output_tokens):
    forwarded = []

    def upstream(request):
        pending = list(tmp_path.glob("main/task-1/*.json"))
        assert len(pending) == 1
        assert json.loads(pending[0].read_text())["state"] == "started"
        forwarded.append(request)
        assert request.headers["Authorization"] == "Bearer upstream-secret"
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "enabled"}
        assert body["max_tokens"] == output_tokens
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}],
                                        "usage": {"prompt_tokens": 11, "completion_tokens": 2,
                                                  "total_tokens": 13}})

    real_client = httpx.Client
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(upstream), **kwargs))
    gateway = model_gateway.Gateway(tmp_path, "http://upstream.test", "upstream-secret", "local-token", requests=1,
                                    output_tokens=output_tokens)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/v1/main/task-1/chat/completions"
    try:
        assert send(url, key="wrong")[0] == 401
        assert send(url)[0] == 200
        assert send(url)[0] == 402
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


@pytest.mark.parametrize("same_task", [False, True])
def test_gateway_bounded_parallelism_and_per_task_budget(monkeypatch, tmp_path, same_task):
    release = threading.Event()
    reached = threading.Event()
    lock = threading.Lock()
    active = peak = calls = 0

    def upstream(request):
        nonlocal active, peak, calls
        with lock:
            active += 1
            calls += 1
            peak = max(peak, active)
            if active == (1 if same_task else 2):
                reached.set()
        assert release.wait(3)
        with lock:
            active -= 1
        return httpx.Response(200, json={"choices": [], "usage": {"total_tokens": 13}})

    real_client = httpx.Client
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(upstream), **kwargs))
    gateway = model_gateway.Gateway(tmp_path, "http://upstream.test", "provider", "local-token",
                                    concurrency=2, requests=1)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with ThreadPoolExecutor(3) as pool:
            futures = [pool.submit(send, f"http://127.0.0.1:{server.server_port}/v1/main/"
                                   f"{'same' if same_task else index}/chat/completions") for index in range(3)]
            try:
                assert reached.wait(2), "Independent episodes must reach upstream concurrently"
            finally:
                release.set()
            statuses = sorted(f.result()[0] for f in futures)
        assert statuses == ([200, 402, 402] if same_task else [200, 200, 200])
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert peak == (1 if same_task else 2)
    assert calls == (1 if same_task else 3)
    assert sum(item["requests"] for item in gateway.counts.values()) == calls
    assert all(item["tokens"] == 13 and item["missing_usage"] == 0 for item in gateway.counts.values())


def test_native_gateway_preserves_decoding_parallelism_and_unknown_usage(monkeypatch, tmp_path):
    release, reached = threading.Event(), threading.Event()
    lock = threading.Lock()
    count = 0

    def upstream(request):
        nonlocal count
        body = json.loads(request.content)
        assert body["max_tokens"] == 65536 and body["temperature"] == 1.0
        assert "reasoning_effort" not in body  # No policy injected by the meter.
        with lock:
            count += 1
            index = count
            if count == 2:
                reached.set()
        assert release.wait(3)
        return httpx.Response(200, json={"choices": [], **({} if index == 1 else {"usage": {"total_tokens": 13}})})

    real_client = httpx.Client
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(upstream), **kwargs))
    gateway = model_gateway.Gateway(tmp_path, "http://upstream.test", "provider", "local-token",
                                    concurrency=2, requests=1, tokens=1, native_settings=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/v1/native/same/chat/completions"
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(send, url, extra={"max_tokens": 65536, "temperature": 1.0}) for _ in range(2)]
            try:
                assert reached.wait(2), "Native same-task workflow calls must overlap"
            finally:
                release.set()
            assert all(f.result()[0] == 200 for f in futures)
        assert send(url, extra={"max_tokens": 65536, "temperature": 1.0})[0] == 200
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert gateway.counts["native/same"] == {"requests": 3, "tokens": 26, "missing_usage": 1}


def test_partial_nonstream_response_becomes_valid_502_not_broken_200(monkeypatch, tmp_path):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"choices":['
            raise httpx.RemoteProtocolError("Truncated upstream")

    real_client = httpx.Client
    monkeypatch.setattr(model_gateway.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=BrokenStream())), **kwargs))
    gateway = model_gateway.Gateway(tmp_path, "http://upstream.test", "provider", "local-token")
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        status, body = send(f"http://127.0.0.1:{server.server_port}/v1/main/q1/chat/completions")
        assert status == 502 and "error" in json.loads(body)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    record = json.loads(next(tmp_path.glob("main/q1/*.json")).read_text())
    assert record["error_type"] == "RemoteProtocolError" and not record["usage"]
