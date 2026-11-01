"""Offline plumbing check: scripted decisions + real WorkBench tools/evaluator.

This deliberately does NOT solve the benchmark task. It must receive a failing
state score, proving that a completed runtime is not incorrectly scored correct.
No actor receives reference actions and no external API is called.
"""
import json
from pathlib import Path

from run_adaptive_workbench import load_benchmark, CONTEXT
from calc.adaptive import AdaptiveRuntime
from calc.llm import ChatResponse, Usage


def tool(name, args):
    return ChatResponse({"role": "assistant", "content": None, "tool_calls": [{
        "id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "tool_calls", Usage(), 0)


def answer(text):
    return ChatResponse({"role": "assistant", "content": text}, "stop", Usage(), 0)


class Scripted:
    model = "offline-scripted"

    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, *args, **kwargs):
        return next(self.responses)


def main():
    repo = Path("D:/CALC-experiments/upstreams/MANTA-native")
    data = Path("D:/CALC-experiments/data/workbench")
    benchmark, sandbox_type, format_call, _ = load_benchmark(repo, data)
    task = benchmark.load_tasks()[0]
    sandbox = sandbox_type(data)
    available = benchmark._build_tools(sandbox, task.metadata["domains"])
    mapping = {t["name"].replace(".", "__"): t for t in available}
    actions = []

    def invoke(name, arguments):
        spec = mapping[name]
        actions.append(format_call(spec["name"], arguments))
        return spec["handler"](arguments)

    strong = Scripted([
        tool("collaborate", {"operation": "delegate", "pattern": "parallel", "reason": "exercise isolation",
                             "branches": [{"goal": "Read directory records for Alex"}]}),
        tool("collaborate", {"operation": "fold", "sources": ["agent_1"], "receiver": "main",
                             "reason": "exercise parent continuation"}),
        tool("company_directory__find_email_address", {"name": "Alex"}),
        answer("Offline plumbing check finished; requested benchmark changes were not performed.")])
    weak = Scripted([tool("company_directory__find_email_address", {"name": "Alex"}),
                     tool("company_directory__find_email_address", {"name": "Alex"})])
    runtime = AdaptiveRuntime(strong=strong, weak=weak, invoke=invoke, max_waves=8,
        environment_context=CONTEXT, tools=[{"type": "function", "function": {
            "name": name, "description": t["description"], "parameters": t["parameters"]}}
            for name, t in mapping.items()])
    result = runtime.run(str(task.prompt))
    evaluation = benchmark.evaluate(task, result["answer"], run_metadata={"function_calls": actions})
    assert result["status"] == "answered"
    assert result["loops"]["agent_1"]["status"] == "folded"
    assert [e["agent"] for e in result["events"] if e["event"] == "tool_result"] == ["agent_1", "agent_1", "main"]
    assert evaluation.success is False
    print(json.dumps({"check": "passed", "external_api_calls": 0, "scripted_decisions": len(result["calls"]),
                      "real_sandbox_tool_calls": len(actions), "fold_then_parent_tool": True,
                      "task_completion": True, "benchmark_success": evaluation.success,
                      "note": "offline plumbing validation; not a model benchmark result"}, indent=2))


if __name__ == "__main__":
    main()
