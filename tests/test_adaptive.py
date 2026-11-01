import copy
import json
import threading

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage


def response(text="done", tool=None, args=None, finish=None, usage=True):
    message = {"role": "assistant", "content": text if tool is None else None}
    if tool:
        message["tool_calls"] = [{"id": "call1", "type": "function", "function": {
            "name": tool, "arguments": json.dumps(args or {})}}]
    return ChatResponse(message, finish or ("tool_calls" if tool else "stop"),
                        Usage.from_response({"prompt_tokens": 5, "completion_tokens": 2} if usage else None), 0)


class Scripted:
    model = "offline-scripted-not-a-benchmark-model"

    def __init__(self, items):
        self.items = iter(items)
        self.received = []

    def complete(self, messages, **kwargs):
        self.received.append(copy.deepcopy(messages))
        item = next(self.items)
        if isinstance(item, Exception):
            raise item
        return item


def runtime(strong=None, weak=None, **kw):
    return AdaptiveRuntime(strong=strong or Scripted([]), weak=weak or Scripted([]),
                           tools=kw.pop("tools", []), invoke=kw.pop("invoke", lambda n, a: a), **kw)


def test_parallel_workers_run_concurrently_and_parent_gets_results():
    barrier = threading.Barrier(2)

    class Workers:
        def complete(self, messages, **kw):
            barrier.wait(timeout=3)
            return response("source checked")

    strong = Scripted([response(tool="collaborate", args={"operation": "delegate", "reason": "independent",
                       "pattern": "parallel", "branches": [{"goal": "A"}, {"goal": "B"}]}), response("final")])
    result = runtime(strong, Workers(), concurrency=2, max_waves=5).run("question")
    assert result["status"] == "answered"
    assert result["usage"]["model_requests"] == 4
    assert len(result["loops"]) == 3
    assert "source checked" in json.dumps(strong.received[-1])


def test_sequence_passes_previous_result_without_leaking_it_early():
    strong = Scripted([response(tool="collaborate", args={"operation": "delegate", "reason": "dependency",
                       "pattern": "sequence", "branches": [{"goal": "find ID"}, {"goal": "use ID"}]}),
                       response(tool="collaborate", args={"operation": "wait", "reason": "dependency running"}), response()])
    weak = Scripted([response("ID=123"), response("used 123")])
    result = runtime(strong, weak, max_waves=6).run("task")
    assert "ID=123" not in json.dumps(weak.received[0])
    assert "ID=123" in json.dumps(weak.received[1])
    assert result["status"] == "answered"


def test_fold_transfers_work_capability_archive_and_next_tool_runs_in_parent():
    strong = Scripted([
        response(tool="collaborate", args={"operation": "delegate", "reason": "explore", "pattern": "parallel",
                                         "branches": [{"goal": "investigate", "skills": ["lookup"]}]}),
        response(tool="collaborate", args={"operation": "wait", "reason": "worker checking"}),
        response(tool="review_change", args={"approve": True, "reason": "parent has cross-branch facts"}),
        response(tool="read_history", args={"agent": "agent_1", "offset": 0}),
        response(tool="load_skill", args={"name": "lookup"}),
        response(tool="lookup", args={"id": "42"}), response("final")])
    weak = Scripted([response(tool="lookup", args={"id": "41"}),
                     response(tool="collaborate", args={"operation": "fold", "reason": "need parent context",
                                                       "sources": ["agent_1"], "receiver": "main"})])
    actual = []
    rt = runtime(strong, weak, max_waves=10,
        tools=[function("lookup", "look up", {"id": {"type": "string"}}, ["id"])],
        invoke=lambda n, a: actual.append(a["id"]) or {"id": a["id"]},
        skills={"lookup": {"description": "lookup procedure", "body": "read IDs exactly"}})
    result = rt.run("task")
    assert result["status"] == "answered"
    assert actual == ["41", "42"]
    assert rt.loops["agent_1"].status == "folded"
    assert "lookup" in rt.loops["main"].skills
    assert [e["agent"] for e in result["events"] if e["event"] == "tool_result"] == ["agent_1", "main"]
    assert result["usage"]["model_requests"] == 9  # includes strong review and parent checkpoint


def test_merge_removes_one_loop_and_preserves_original_history():
    rt = runtime()
    root = rt._new("task", None, "strong", [])
    a = rt._new("first", root.id, "strong", [])
    b = rt._new("second", root.id, "weak", [])
    b.messages.append({"role": "user", "content": "do not lose this clue"})
    rt.change(a.id, {"operation": "merge", "reason": "coupled", "sources": [b.id], "receiver": a.id})
    assert b.status == "merged"
    assert "second" in a.goal
    assert "do not lose this clue" in json.dumps(rt._tool(a, "read_history", {"agent": b.id, "offset": 0}))


def test_invalid_migration_is_atomic_and_does_not_call_judge():
    rt = runtime()
    root = rt._new("task", None, "strong", [])
    a = rt._new("first", root.id, "weak", [])
    rt._new("unfinished child", a.id, "weak", [])
    before = copy.deepcopy(rt.loops)
    with pytest.raises(ValueError, match="child scopes"):
        rt.change(root.id, {"operation": "fold", "reason": "test", "sources": [a.id], "receiver": root.id})
    assert before == rt.loops
    assert rt.calls == []


def test_missing_usage_is_not_counted_as_known_zero_and_truncation_not_answer():
    result = runtime(Scripted([response("partial", finish="length", usage=False)])).run("task")
    assert result["answer"] == ""
    assert result["status"] == "blocked_or_failed"
    assert result["usage"]["unreported_usage_requests"] == 1
    assert result["correctness"] == "not_evaluated"


def test_transport_error_records_attempt_and_no_hidden_retry():
    model = Scripted([TimeoutError("not logged")])
    result = runtime(model).run("task")
    assert result["usage"]["model_requests"] == 1
    assert result["usage"]["unreported_usage_requests"] == 1
    assert result["status"] == "blocked_or_failed"


def test_worker_can_delegate_and_child_returns_to_worker():
    strong = Scripted([
        response(tool="collaborate", args={"operation": "delegate", "reason": "independent", "pattern": "parallel",
                                         "branches": [{"goal": "work"}]}),
        response(tool="review_change", args={"approve": True, "reason": "independent check"}), response("global")])
    weak = Scripted([
        response(tool="collaborate", args={"operation": "delegate", "reason": "check", "pattern": "parallel",
                                         "branches": [{"goal": "subwork"}]}), response("child result"), response("worker result")])
    result = runtime(strong, weak, max_waves=8, environment_context="date=2023-11-30").run("question")
    assert result["loops"]["agent_2"]["parent"] == "agent_1"
    assert "child result" in json.dumps(weak.received[-1])
    assert all("date=2023-11-30" in m[0]["content"] for m in weak.received)
    assert result["answer"] == "global"


def test_folded_sequence_scope_releases_dependent_before_parent_final():
    rt = runtime()
    main = rt._new("task", None, "strong", [])
    a = rt._new("find ID", main.id, "weak", [])
    b = rt._new("use ID", main.id, "weak", [])
    b.dependencies = [a.id]
    rt.change(main.id, {"operation": "fold", "reason": "shared context", "sources": [a.id], "receiver": main.id})
    assert b.dependencies == [a.id]
    assert not rt._satisfied(a.id)
    rt._tool(main, "complete_transferred_work", {"source": a.id, "result": "ID=123"})
    rt._unblock()
    assert rt._satisfied(a.id) and main.status != "done"
    assert "ID=123" in json.dumps(b.messages)


def test_main_can_fold_at_child_progress_checkpoint_without_worker_request():
    strong = Scripted([
        response(tool="collaborate", args={"operation": "delegate", "reason": "explore", "pattern": "parallel",
                                         "branches": [{"goal": "investigate"}]}),
        response(tool="collaborate", args={"operation": "fold", "reason": "same context now sufficient",
                                         "sources": ["agent_1"], "receiver": "main"}), response("global")])
    weak = Scripted([response(tool="lookup", args={}), response(tool="lookup", args={})])
    rt = runtime(strong, weak, tools=[function("lookup", "read", {}, [])], max_waves=6)
    result = rt.run("task")
    assert result["answer"] == "global"
    assert result["loops"]["agent_1"]["status"] == "folded"
    assert "Child checkpoint" in json.dumps(strong.received[1])
