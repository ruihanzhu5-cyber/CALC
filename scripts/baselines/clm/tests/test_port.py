"""Offline author-port contract tests; never call the public model endpoint."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from harbor.models.task.task import Task

from calc_clm_port.agent import DeepSeekClmAgent, project_deepseek_messages
from calc_clm_port.pack_tasks import pack, selected_tasks


def test_gold_is_not_packaged_and_harbor_schema_is_valid(tmp_path):
    source = tmp_path / "queries.jsonl"
    source.write_text(json.dumps({"query_id": "q/1", "query": "Find the public fact",
                                  "answer": "HIDDEN_GOLD_SENTINEL", "qrels": ["HIDDEN_QREL"]}) + "\n")
    manifest = pack(source, tmp_path / "tasks")
    target = tmp_path / "tasks" / manifest["tasks"][0]["directory"]
    task = Task(target)
    assert "Find the public fact" in task.instruction
    content = "\n".join(path.read_text() for path in target.rglob("*") if path.is_file())
    assert "HIDDEN_GOLD_SENTINEL" not in content and "HIDDEN_QREL" not in content
    assert "DEEPSEEK_API_KEY" not in (target / "environment" / "Dockerfile").read_text()
    assert "network_mode: host" in (target / "environment" / "docker-compose.yaml").read_text()
    assert b"\r\n" not in (target / "tests" / "test.sh").read_bytes()
    with pytest.raises(FileExistsError):
        pack(source, tmp_path / "tasks")


def test_selection_does_not_silently_add_unknown_tasks(tmp_path):
    source = tmp_path / "queries.jsonl"
    source.write_text(json.dumps({"query_id": 1, "query": "Find this"}) + "\n")
    assert selected_tasks(source, ["1"], None) == [{"query_id": "1", "query": "Find this"}]
    with pytest.raises(ValueError, match="unknown task IDs"):
        selected_tasks(source, ["missing"], None)


def test_wire_projection_preserves_real_reasoning_and_marks_edited_notes():
    source = [
        {"role": "system", "content": "Pinned system"},
        {"role": "user", "content": "Pinned question"},
        {"role": "assistant", "content": "", "reasoning_content": "Retained original reasoning",
         "tool_calls": [{"id": "a", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": "Observation"},
        {"role": "assistant", "content": "A context-edited summary without original protocol fields"},
    ]
    projected, converted = project_deepseek_messages(source)
    assert projected[:2] == source[:2]
    assert projected[2]["reasoning_content"] == "Retained original reasoning"
    assert projected[2]["tool_calls"] == source[2]["tool_calls"]
    assert projected[3]["tool_call_id"] == "a"
    assert projected[4]["role"] == "user"
    assert source[4]["role"] == "assistant"
    assert converted == 1


def test_transport_uses_metered_proxy_token_and_thinking_high_without_real_key(monkeypatch, tmp_path):
    captured = {}
    class FakeUsage:
        def model_dump(self):
            return {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.complete))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            captured["client"]["http_client"].close()
            return False
        def complete(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(id="offline-response", usage=FakeUsage())
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("CALC_GATEWAY_KEY", "offline-local-token")
    monkeypatch.setattr("calc_clm_port.agent.OpenAI", FakeOpenAI)
    agent = DeepSeekClmAgent(logs_dir=tmp_path, model_name="openai/deepseek-flash",
                            api_base="http://127.0.0.1:8767/v1/run/q1",
                            context_budget_tokens=28672, cost_metric="usd")
    asyncio.run(agent._query_with_retry("openai/deepseek-flash", [{"role": "user", "content": "Question"}]))
    assert captured["client"]["api_key"] == "offline-local-token"
    assert captured["client"]["base_url"].endswith("/v1/run/q1")
    assert captured["client"]["http_client"].trust_env is False
    assert captured["request"]["model"] == "deepseek-flash"
    assert captured["request"]["reasoning_effort"] == "high"
    assert captured["request"]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "temperature" not in captured["request"]
    log = (tmp_path / "deepseek_transport.jsonl").read_text()
    assert "offline-local-token" not in log
    assert json.loads(log)["usage"]["total_tokens"] == 15
