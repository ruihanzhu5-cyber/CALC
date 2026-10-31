"""Run pinned, unmodified POrchestra core on the shared BCP tool service.

This is a benchmark environment/runner adapter, not a reimplementation of the
MainAgent, DelegateTaskTool, session revision protocol, or memory bus.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import chdir
from pathlib import Path
from types import SimpleNamespace

SOURCE_COMMIT = "371aef619aec6f2918690a2fbaf9bf797b3025d3"
EXP_ROOT = Path(os.environ.get("CALC_EXP_ROOT", "D:/CALC-experiments" if os.name == "nt" else "/mnt/d/CALC-experiments"))
TOOLS = [
    {"name": "search", "description": "Search the official BrowseComp-Plus BM25 index. Returns top 10 document snippets, each at most 512 Qwen3 tokens.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "get_document", "description": "Read an indexed document by docid. Returns up to 8192 Qwen3 tokens from the shared document reader.",
     "parameters": {"type": "object", "properties": {"docid": {"type": "string"}}, "required": ["docid"]}},
]


class TraceSink:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.sequence = 0

    def append(self, event_name: str, **payload):
        self.sequence += 1
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"sequence": self.sequence, "elapsed_seconds": time.monotonic() - self.started,
                                     "event_type": event_name, **payload}, ensure_ascii=False, default=str) + "\n")


def native_types(source_root: Path):
    sys.path.insert(0, str(source_root))
    # Upstream's module-level logger opens workspace/logs relative to cwd.
    # Keep that original logger and its output outside the source checkout.
    runtime_dir = EXP_ROOT / "runs" / "porchestra" / "_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with chdir(runtime_dir):
        from base.engine.async_llm import AsyncLLM, LLMsConfig, create_llm_instance
        from benchmark.common.env import BasicInfo, Environment
        from porchestra.main_agent import MainAgent
        from porchestra.tools.delegate import DelegateTaskTool
    return AsyncLLM, LLMsConfig, create_llm_instance, BasicInfo, Environment, MainAgent, DelegateTaskTool


def make_environment(BasicInfo, Environment):
    import httpx

    class BCPEnvironment(Environment):
        def __init__(self, query_id, query, service_url, *, max_tool_calls=60, session_steps=30, trace=None):
            self.query_id = str(query_id)
            self.original_question = query
            self.instruction = query
            self.service_url = service_url.rstrip("/")
            self.max_tool_calls = max_tool_calls
            self.session_steps = session_steps
            self.tool_calls = 0
            self.trace = trace
            self.http = httpx.Client(timeout=120, trust_env=False)

        def get_basic_info(self):
            return BasicInfo(env_id=self.query_id, instruction=self.instruction,
                             action_space="Available actions\n\n" + "\n\n".join(
                                 "### " + tool["name"] + "\n" + tool["description"] + "\nParameters: "
                                 + json.dumps(tool["parameters"]) for tool in TOOLS), max_steps=self.session_steps,
                             meta_data={"original_question": self.original_question, "benchmark": "BrowseComp-Plus",
                                        "tool_calls_used": self.tool_calls, "max_tool_calls": self.max_tool_calls})

        def reset(self, seed=None):
            # Native delegate calls reset for every new session. BCP retrieval
            # is stateless, so only its initial observation resets. The task's
            # total tool budget must never reset when a worker is replaced.
            return {"instruction": self.instruction, "tool_calls_used": self.tool_calls,
                    "remaining_tool_calls": max(0, self.max_tool_calls - self.tool_calls)}

        def step(self, action):
            name = action.get("action")
            params = action.get("params") or {}
            if self.tool_calls >= self.max_tool_calls:
                return {"error": "task retrieval tool budget exhausted"}, 0.0, True, {"budget_exhausted": True}
            self.tool_calls += 1
            before = time.monotonic()
            try:
                if name == "search":
                    response = self.http.post(self.service_url + "/retrieve", json={"query": params["query"]})
                elif name == "get_document":
                    response = self.http.post(self.service_url + "/document", json={"docid": params["docid"]})
                else:
                    raise ValueError(f"Unknown tool: {name}")
                response.raise_for_status()
                observation = response.json()
            except (KeyError, ValueError, httpx.HTTPError) as error:
                observation = {"error": f"{type(error).__name__}: {error}"}
            info = {"tool_calls_used": self.tool_calls, "tool_elapsed_seconds": time.monotonic() - before}
            if self.trace:
                self.trace.append("bcp_tool", action=action, observation=observation, **info)
            return observation, 0.0, self.tool_calls >= self.max_tool_calls, info

    return BCPEnvironment


def make_complete_tool():
    # MainAgent tools need name/parameters and an async callable; no replacement
    # of any upstream class or protocol is necessary for final submission.
    class Complete:
        name = "complete"
        description = "Submit the concise final answer to the original question."
        def __init__(self):
            self.parameters = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
            self.answer = None

        async def __call__(self, answer: str):
            self.answer = str(answer)
            return {"answer": self.answer, "submitted": True}
    return Complete()


async def run_task(args, task):
    _AsyncLLM, LLMsConfig, create_llm_instance, BasicInfo, Environment, MainAgent, DelegateTaskTool = native_types(args.source_root)
    query_id = str(task["query_id"])
    out = args.output_dir / query_id
    out.mkdir(parents=True, exist_ok=True)
    trace = TraceSink(out / "trace.jsonl")
    # The task-scoped proxy meters Main, worker, memory-compression and trace-
    # summary calls together. No real provider credential enters this runner.
    base_url = args.llm_proxy.rstrip("/") + "/" + query_id
    gateway_key = os.environ.get("CALC_GATEWAY_KEY")
    if not gateway_key:
        raise RuntimeError("CALC_GATEWAY_KEY is required for the local metering proxy; use invoke_wsl_experiment.ps1 to inject it.")
    model_config = {"model": args.model, "base_url": base_url, "api_key": gateway_key,
                    "temperature": args.temperature, "top_p": 1, "timeout": 300}
    LLMsConfig._default_config = LLMsConfig({args.model: model_config})
    llm = create_llm_instance(model_config)
    env_class = make_environment(BasicInfo, Environment)
    env = env_class(query_id, task["query"], args.service_url,
                    max_tool_calls=args.max_tool_calls, session_steps=args.session_steps, trace=trace)
    delegate = DelegateTaskTool(env=env, models=[args.model], benchmark_type="gaia",
                                default_max_steps=args.session_steps, max_total_steps=args.max_subagent_steps,
                                memory_mode="compressed", live_trace=trace)
    complete = make_complete_tool()
    main = MainAgent(llm=llm, sub_models=[args.model], tools=[delegate, delegate.make_revise_tool(), complete],
                     subagent_tools=[SimpleNamespace(**tool) for tool in TOOLS],
                     max_attempts=args.max_attempts, benchmark_type="gaia", live_trace=trace)
    main.reset(env.get_basic_info())
    started = time.monotonic()
    error = None
    try:
        for _ in range(args.max_main_decisions):
            await main.step()
            if complete.answer is not None:
                break
    except Exception as exc:  # noqa: BLE001 -- persist per-task infrastructure/model failures before returning
        error = f"{type(exc).__name__}: {exc}"
        trace.append("runner_error", error=error)
    finally:
        delegate._close_session()
        env.http.close()
    result = {"query_id": query_id, "answer": complete.answer or "", "submitted": complete.answer is not None,
              "error": error, "elapsed_seconds": time.monotonic() - started,
              "tool_calls": env.tool_calls, "main_decisions": main.decision_step,
              "subagent_steps": delegate.total_steps_used, "source_commit": SOURCE_COMMIT,
              "native_main_history": main.history,
              "limits": {"max_main_decisions": args.max_main_decisions, "max_tool_calls": args.max_tool_calls,
                         "session_steps": args.session_steps, "max_subagent_steps": args.max_subagent_steps,
                         "max_attempts": args.max_attempts},
              "note": "Native MainAgent/DelegateTaskTool/ReActSubAgent; BCP tool environment port. No correctness score computed."}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"query_id": query_id, "submitted": result["submitted"], "error": error,
                      "tool_calls": env.tool_calls, "elapsed_seconds": result["elapsed_seconds"]}))
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("/opt/calc/upstreams/POrchestra"))
    parser.add_argument("--tasks", type=Path, default=EXP_ROOT / "bench" / "browsecomp-plus" / "tasks" / "first20.dev.jsonl")
    parser.add_argument("--query-id")
    parser.add_argument("--output-dir", type=Path, default=EXP_ROOT / "runs" / "porchestra")
    parser.add_argument("--service-url", default="http://127.0.0.1:8765")
    parser.add_argument("--llm-proxy", default="http://127.0.0.1:8767/v1/porchestra")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--max-main-decisions", type=int, default=100)
    parser.add_argument("--max-tool-calls", type=int, default=200)
    parser.add_argument("--session-steps", type=int, default=30)
    parser.add_argument("--max-subagent-steps", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=10)
    parser.add_argument("--check", action="store_true", help="Import native classes and check retrieval health only. No LLM calls.")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.check:
        import httpx
        native_types(args.source_root)
        health = httpx.get(args.service_url + "/health", timeout=30, trust_env=False)
        health.raise_for_status()
        print(json.dumps({"native_import": "ok", "source_commit": SOURCE_COMMIT, "retriever": health.json(), "llm_calls": 0}))
        return
    if not args.query_id:
        raise SystemExit("Choose exactly one preregistered task with --query-id; this runner never starts a batch implicitly.")
    tasks = [json.loads(line) for line in args.tasks.read_text(encoding="utf-8").splitlines() if line.strip()]
    task = next((row for row in tasks if str(row["query_id"]) == args.query_id), None)
    if task is None:
        raise SystemExit("query-id is absent from the selected task manifest")
    asyncio.run(run_task(args, task))


if __name__ == "__main__":
    main()
