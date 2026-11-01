"""Fixed GAIA2 cases, original MANTA self_evolved or CALC; no automatic reruns.

Default preflight calls no model and produces no experimental score.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calc.adaptive import AdaptiveRuntime  # noqa: E402
from calc.benchmarks.gaia2 import (Gaia2Adapter, JudgeEngine, ClockedClient,  # noqa: E402
                                   ARE_COMMIT, MANTA_COMMIT, PUBLIC_CONTEXT)
from calc.llm import OpenAICompatibleClient, Usage, aggregate_usage  # noqa: E402


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def verify(repo, commit):
    actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if actual != commit or subprocess.call(["git", "-c", "core.autocrlf=true", "-c", "core.filemode=false", "-C", str(repo), "diff", "--quiet", "HEAD"]):
        raise RuntimeError(f"upstream source mismatch: {repo}")


def manta_runner(cfg, adapter, emit):
    sys.path.insert(0, cfg["manta_repo"])
    from MAS.config import load_experiment_config
    from MAS.llm import OpenRouterLLMClient
    from MAS.runner import MASRunner
    from openai import OpenAI
    native_cfg = load_experiment_config(cfg["manta_config"])
    native_cfg.openrouter.api_key = os.environ["DEEPSEEK_API_KEY"]
    os.environ["MAS_REQUIRE_LIVE_LLM"] = "1"
    for name in ("MAS_DISABLE_LIVE_LLM", "OPENROUTER_MAX_TOKENS", "OPENROUTER_REASONING_EFFORT",
                 "OPENROUTER_TEMPERATURE", "MAS_LLM_MAX_RETRIES"):
        if name in os.environ:
            raise RuntimeError(f"unexpected MANTA environment override: {name}")
    native = OpenRouterLLMClient(native_cfg.openrouter, native_cfg.models)
    # Replace only HTTP transport; original prompts, tool loops, topology and audit remain native.
    http_client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                         base_url=cfg["base_url"], timeout=600, max_retries=0)

    class Completions:
        def create(self, **kwargs):
            body = dict(kwargs)
            messages = [dict(m) for m in body["messages"]]
            messages.append({"role": "user", "content": "Current public environment updates:\n" + adapter.public_snapshot()})
            body["messages"] = messages
            # OpenRouter routing fields have no meaning on the official DeepSeek endpoint.
            extra = dict(body.get("extra_body") or {})
            extra.pop("provider", None)
            extra.pop("models", None)
            body["extra_body"] = extra
            adapter.begin_request()
            try:
                result = http_client.chat.completions.create(**body)
                emit({"event": "actor_request", "usage": Usage.from_response(
                    result.usage.model_dump() if result.usage else None).to_dict(),
                    "finish_reason": result.choices[0].finish_reason,
                    "message": result.choices[0].message.model_dump()})
                return result
            except Exception as exc:
                emit({"event": "actor_request", "usage": {}, "error": type(exc).__name__})
                raise
            finally:
                adapter.end_request()

    native.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    return MASRunner(native_cfg, native), http_client


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--method", choices=["calc", "manta"], required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    cfg = json.loads(args.config.read_text())
    os.environ["DEMO_FS_PATH"] = cfg["filesystem_root"]
    verify(cfg["are_repo"], ARE_COMMIT)
    verify(cfg["manta_repo"], MANTA_COMMIT)
    lock = json.loads(Path(cfg["task_lock"]).read_text())
    if args.task not in lock["task_ids"]:
        raise ValueError("task is not in the fixed five-case manifest")
    path = Path(cfg["task_dir"]) / (args.task + ".json")
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock["sha256"][path.name]:
        raise ValueError("task hash mismatch")
    output = Path(cfg["output_dir"]) / ("execute" if args.execute else "preflight") / args.method / args.task
    if not args.execute:
        output = output / str(time.time_ns())
    output.mkdir(parents=True, exist_ok=False)
    rows, loglock = [], threading.Lock()
    log = (output / "trace.jsonl").open("w", encoding="utf-8")
    def emit(event):
        with loglock:
            event = {"wall_time": time.time(), **event}
            log.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            log.flush()
            if event["event"] in {"actor_request", "judge_request"}:
                rows.append(event)
    write(output / "manifest.json", {"config": cfg, "method": args.method, "task_id": args.task,
        "are_commit": ARE_COMMIT, "manta_commit": MANTA_COMMIT, "data_lock": lock,
        "source_sha256": {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in [Path(__file__), ROOT / 'src/calc/adaptive.py', ROOT / 'src/calc/benchmarks/gaia2.py']},
        "preflight": not args.execute})
    started = time.perf_counter()
    adapter, actor_client, judge_client, manta_http = None, None, None, None
    try:
        if args.execute:
            judge_client = OpenAICompatibleClient(cfg["base_url"], cfg["model"],
                os.environ["DEEPSEEK_API_KEY"], temperature=0, timeout=600)
        def no_model(*a, **k):
            raise RuntimeError("preflight attempted an unauthorized model request")
        judge = JudgeEngine(judge_client, emit) if args.execute else no_model
        adapter = Gaia2Adapter(path, judge, emit, preflight=not args.execute)
        initial = adapter.wait_events()
        if not initial:
            raise RuntimeError("environment ended without initial public request")
        if not args.execute:
            # Exercise actual public tool dispatch; not an attempted task solution.
            available = [t for t in adapter.tools if not adapter.app_tools[t['function']['name']].write_operation]
            if not available:
                raise RuntimeError("no read-only tool catalog")
            # No arbitrary mutation or model call; verify schema serialization and MANTA imports.
            json.dumps(adapter.tools)
            adapter.invoke("SystemApp__get_current_time", {})
            sys.path.insert(0, cfg["manta_repo"])
            from MAS.config import load_experiment_config
            native_cfg = load_experiment_config(cfg["manta_config"])
            native_cfg.validate()
            write(output / "preflight.json", {"status": "passed", "model_requests": 0,
                "tools": len(adapter.tools), "notifications": len(initial),
                "native_topology": native_cfg.mas.topology,
                "repair_budget": native_cfg.self_evolved.repair_budget,
                "max_turns": native_cfg.self_evolved.max_turns,
                "note": "Environment/schema/import preflight only; no benchmark score"})
            return
        instruction = PUBLIC_CONTEXT + "\n" + json.dumps(initial, ensure_ascii=False)
        if args.method == "calc":
            actor_client = OpenAICompatibleClient(cfg["base_url"], cfg["model"],
                os.environ["DEEPSEEK_API_KEY"], temperature=0, timeout=600)
            client = ClockedClient(actor_client, adapter, emit)
            runtime = AdaptiveRuntime(strong=client, weak=client, tools=adapter.tools,
                invoke=adapter.invoke, external_events=adapter.pending,
                event_sink=lambda e: emit({**e, "runtime_event": True}),
                environment_context=PUBLIC_CONTEXT, **cfg["runtime"])
        else:
            runner, manta_http = manta_runner(cfg, adapter, emit)
            tools = [{"name": t["function"]["name"], "description": t["function"]["description"],
                      "parameters": t["function"]["parameters"],
                      "side_effect": bool(adapter.app_tools[t["function"]["name"]].write_operation),
                      "handler": lambda a, name=t["function"]["name"]: adapter.invoke(name, a)}
                     for t in adapter.tools]
        turns = []
        while not adapter.stopped():
            before = adapter.sent
            if args.method == "calc":
                result = runtime.run(instruction, resume=bool(turns))
                answer = result["answer"]
                write(output / f"turn_{len(turns)}.json", result)
            else:
                task = SimpleNamespace(task_id=args.task, prompt=instruction, reference_answer="", metadata={})
                result = runner.run_task(task, 0, 42, tools=tools,
                    max_tool_iterations=cfg["manta_max_tool_iterations"], benchmark_name="gaia2")
                answer = result.final_answer
                write(output / f"turn_{len(turns)}.json", asdict(result))
            turns.append(answer)
            if not answer:
                raise RuntimeError("actor ended without an answer")
            if adapter.sent == before and not adapter.stopped():
                adapter.invoke("AgentUserInterface__send_message_to_user", {"content": answer})
            if adapter.scenario.nb_turns is not None and adapter.sent >= adapter.scenario.nb_turns:
                break
            events = adapter.wait_events()
            if not events:
                break
            instruction = PUBLIC_CONTEXT + "\nNew user/environment turn:\n" + json.dumps(events, ensure_ascii=False)
        evaluation = adapter.evaluate()
        write(output / "evaluation.json", asdict(evaluation))
        write(output / "result.json", {"status": "completed", "answers": turns,
            "success": evaluation.success, "wall_seconds": time.perf_counter() - started,
            "actor_usage": aggregate_usage([r for r in rows if r["event"] == "actor_request"]),
            "judge_usage": aggregate_usage([r for r in rows if r["event"] == "judge_request"])})
    except Exception as exc:
        write(output / "failure.json", {"type": type(exc).__name__, "detail": str(exc),
            "wall_seconds": time.perf_counter() - started, "usage": aggregate_usage(rows)})
        raise
    finally:
        if adapter:
            # Preserve official event log for independent re-evaluation.
            from are.simulation.data_handler.exporter import JsonScenarioExporter
            exported = JsonScenarioExporter().export_to_json(env=adapter.env,
                scenario=adapter.scenario, scenario_id=args.task, runner_config=None)
            (output / "official_trace.json").write_text(exported, encoding="utf-8")
            adapter.close()
        for client in (actor_client, judge_client, manta_http):
            if client:
                client.close()
        log.close()
    print(json.dumps({"output": str(output), "status": "complete"}))


if __name__ == "__main__":
    main()
