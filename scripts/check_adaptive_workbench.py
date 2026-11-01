"""Offline plumbing check: scripted decisions + real WorkBench tools/evaluator.

This deliberately does NOT solve the benchmark task. It must receive a failing
state score, proving that a completed runtime is not incorrectly scored correct.
No actor receives reference actions and no external API is called.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from calc.benchmarks.workbench import load_benchmark, WorkBenchAdapter
from calc.benchmarks.session import adaptive_runtime
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

    def complete(self, messages, **kwargs):
        item = next(self.responses)
        result = item(messages) if callable(item) else item
        system = messages[0]["content"]
        checkpoints = json.loads(system.split("Pending progress checkpoints: ")[1].split("\n")[0])
        if not checkpoints:
            return result
        actor = system.split("You are ")[1].split(".")[0]
        state = json.loads(system.split("Current team state: ")[1].split("\n")[0])
        current = next(a for a in state if a["id"] == actor)
        p = {"report_id": f'p{current["event_version"]}',
             "summary": "Scripted plumbing progress only",
             "next_step": "Execute the next scripted action", "evidence_ids": current["evidence_ids"],
             "reason": "Exercise explicit assessment without an extra model call"}
        for call in result.message.get("tool_calls", []):
            if call["function"]["name"] == "collaborate":
                args = json.loads(call["function"]["arguments"])
                args["event_version"] += 1  # report commits before this full-envelope proposal
                args["progress"].update(progress=p["summary"], next_step=p["next_step"])
                call["function"]["arguments"] = json.dumps(args)
        if not result.message.get("tool_calls"):
            p["answer"] = result.message["content"]
            return tool("report_progress", p)
        record = tool("report_progress", p).message["tool_calls"][0]
        record["id"] = "progress"
        result.message["tool_calls"].insert(0, record)
        return result


def change(**proposal):
    def decision(messages):
        system = messages[0]["content"]
        actor = system.split("You are ")[1].split(".")[0]
        state = json.loads(system.split("Current team state: ")[1].split("\n")[0])
        current = next(a for a in state if a["id"] == actor)
        return tool("collaborate", {"event_type": "blocked", "event_version": current["event_version"],
            "progress": current["work"], "evidence_ids": current["evidence_ids"],
            "baseline_next": "worker continues directory lookup", "proposed_next": "parent continues lookup",
            "expected_savings": "test transfer without another worker loop", "risks": "lose independent context",
            "handoff": "preserve raw tool evidence and history", **proposal})
    return decision


def main():
    repo = Path("D:/CALC-experiments/upstreams/MANTA-native")
    data = Path("D:/CALC-experiments/data/workbench")
    benchmark, sandbox_type, format_call, _ = load_benchmark(repo, data)
    task = benchmark.load_tasks()[0]
    adapter = WorkBenchAdapter(benchmark, sandbox_type, format_call, data, task)
    session = adapter.session()

    strong = Scripted([
        change(operation="delegate", pattern="parallel", reason="exercise isolation",
               branches=[{"goal": "Read directory records for Alex"}]),
        change(operation="fold", sources=["agent_1"], receiver="main", reason="exercise parent continuation"),
        tool("company_directory__find_email_address", {"name": "Alex"}),
        tool("complete_transferred_work", {"source": "agent_1", "result": "Directory lookup completed"}),
        answer("Offline plumbing check finished; requested benchmark changes were not performed.")])
    weak = Scripted([tool("company_directory__find_email_address", {"name": "Alex"}),
                     change(operation="continue", reason="report blocked work to parent"),
                     tool("company_directory__find_email_address", {"name": "Alex"})])
    runtime = adaptive_runtime(session.actor_environment(), strong=strong, weak=weak,
                               options={'max_waves': 8, 'progress_checkpoints': True})
    try:
        result = runtime.run(adapter.instruction)
        session.finish()
        evaluation = session.evaluate(result['answer'])
    finally:
        session.close()
    assert result["status"] == "answered"
    assert result["loops"]["agent_1"]["status"] == "folded"
    assert [e["agent"] for e in result["events"] if e["event"] == "tool_result"] == ["agent_1", "agent_1", "main"]
    assert evaluation.success is False
    print(json.dumps({"check": "passed", "external_api_calls": 0, "scripted_decisions": len(result["calls"]),
                      "real_sandbox_tool_calls": len(adapter.actions), "fold_then_parent_tool": True,
                      "task_completion": True, "benchmark_success": evaluation.success,
                      "progress_checkpoints": result["metrics"]["progress_checkpoints"],
                      "task_state_updates": result["metrics"]["task_state_updates"],
                      "note": "offline plumbing validation; not a model benchmark result"}, indent=2))


if __name__ == "__main__":
    main()
