import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import porchestra_bcp as bridge


def test_native_delegate_revise_preserves_session_and_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("CALC_GATEWAY_KEY", "contract-test-no-real-key")
    types = bridge.native_types(Path("/opt/calc/upstreams/POrchestra"))
    AsyncLLM = types[0]
    import porchestra.tools.delegate as native_delegate

    def response(action, params):
        return json.dumps({"action": action, "params": params, "memory": "observed evidence"})

    main_calls = [response("delegate_task", {"task_instruction": "Investigate", "model": "test-model", "tools": ["search", "get_document"]}),
                  response("revise_task", {"context": "Read the found document", "step_budget": 5}),
                  response("complete", {"answer": "test-only"})]
    worker_calls = [response("search", {"query": "test query"}),
                    response("revise", {"state": "A document was found", "action": {"type": "revise", "task_scope": {"operation": "keep", "object": "investigation", "details": "Read document"}, "resource": {"operation": "request", "object": "budget", "details": "Need more steps"}, "request": "continue reading", "reason": "document still unread"}, "evidence": {"summary": "document 123"}}),
                    response("get_document", {"docid": "123"}),
                    response("finish", {"state": "Document read", "action": {"type": "finish", "task_scope": {"operation": "keep", "object": "investigation", "details": "done"}, "resource": {"operation": "keep", "object": "none", "details": "no request"}, "request": "Use document result", "reason": "verified"}, "evidence": {"summary": "test evidence"}})]

    created_workers = []

    class ScriptedLLM(AsyncLLM):
        def __init__(self, calls):
            self.calls = calls
            self.config = SimpleNamespace(model="test-model")

        async def __call__(self, prompt, **kwargs):
            # Native tool selection must retain both schemas even when Main
            # supplies an explicit tools allowlist.
            if self.calls is worker_calls:
                assert "### search" in prompt
                assert "### get_document" in prompt
            return self.calls.pop(0)

        def get_usage_summary(self):
            return {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0}

    def worker_factory(config):
        llm = ScriptedLLM(worker_calls)
        created_workers.append(llm)
        return llm

    monkeypatch.setattr(native_delegate, "create_llm_instance", worker_factory)
    monkeypatch.setattr(bridge, "native_types", lambda root: (types[0], types[1], lambda config: ScriptedLLM(main_calls), *types[3:]))
    original_factory = bridge.make_environment

    def env_factory(BasicInfo, Environment):
        native_env = original_factory(BasicInfo, Environment)

        class LocalEnvironment(native_env):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.http.close()
                self.http = httpx.Client(transport=httpx.MockTransport(self.handle))

            def handle(self, request):
                if request.url.path == "/retrieve":
                    return httpx.Response(200, json={"result": [{"docid": "123", "document": {"title": "Test", "text": "snippet"}}]})
                assert request.url.path == "/document"
                return httpx.Response(200, json={"document": {"docid": "123", "title": "Test", "text": "test evidence"}, "truncated": False})
        return LocalEnvironment

    monkeypatch.setattr(bridge, "make_environment", env_factory)
    args = SimpleNamespace(source_root=Path("/opt/calc/upstreams/POrchestra"), output_dir=tmp_path,
                           llm_proxy="http://127.0.0.1:8767/v1/porchestra", model="test-model", temperature=0,
                           service_url="http://127.0.0.1:8765", max_tool_calls=60, session_steps=30,
                           max_subagent_steps=120, max_attempts=10, max_main_decisions=10)
    result = asyncio.run(bridge.run_task(args, {"query_id": "contract-test", "query": "Test question"}))
    assert result["submitted"] and result["answer"] == "test-only"
    assert result["tool_calls"] == 2
    assert result["subagent_steps"] == 4
    assert len(created_workers) == 1
    assert not main_calls and not worker_calls
    assert [event["attempt"] for event in result["native_main_history"]] == [1, 1]
    assert [event["revision"] for event in result["native_main_history"]] == [0, 1]
