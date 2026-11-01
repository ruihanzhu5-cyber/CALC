"""Run CALC's API-only adaptive loops in MANTA's pinned WorkBench environment.

Default is a credential-free offline preflight. --execute makes paid API calls.
Gold stays in the benchmark adapter and is used only after the actor returns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from calc.adaptive import AdaptiveRuntime  # noqa: E402
from calc.llm import OpenAICompatibleClient  # noqa: E402
from calc.progress import MODES, allowed_operations  # noqa: E402

PIN = "3da40879d690a25459cc401292e5c6f0cc366d84"
CONTEXT = ("Today's date is Thursday, 2023-11-30 and the current time is 00:00:00. "
           "Meetings must not start before 9am or end after 6pm. Use workplace tools to complete the task. "
           "After using tools, provide a brief natural-language confirmation. All tools act on a local sandbox. ")


def load_benchmark(repo: Path, data: Path):
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if commit != PIN:
        raise ValueError(f"expected pinned MANTA commit {PIN}")
    dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], text=True)
    if dirty.strip():
        raise ValueError("pinned MANTA tracked files have local modifications")
    sys.path.insert(0, str(repo.resolve()))
    from benchmark.workbench import WorkBenchBenchmark, WorkBenchSandbox, DATA_FILES, QUERY_FILE_NAMES
    from benchmark.workbench import _format_function_call
    files = [*DATA_FILES, *[f"data/processed/tasks_and_outcomes/v1/{f}" for f in QUERY_FILE_NAMES.values()]]
    missing = [f for f in files if not (data / f).is_file()]
    if missing:
        raise FileNotFoundError(f"local assets missing (no auto-download): {missing}")
    benchmark = WorkBenchBenchmark({"data_dir": str(data), "domain": "multi_domain",
                                    "tasks_version": "v1", "tool_selection": "domains"})
    hashes = {f: hashlib.sha256((data / f).read_bytes()).hexdigest() for f in files}
    return benchmark, WorkBenchSandbox, _format_function_call, hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--mode", choices=sorted(MODES))
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if args.mode:
        cfg["runtime"]["collaboration_mode"] = args.mode
    mode = cfg["runtime"].get("collaboration_mode", "full")
    benchmark, sandbox_type, format_call, hashes = load_benchmark(Path(cfg["manta_repo"]), Path(cfg["data_dir"]))
    tasks = {t.task_id: t for t in benchmark.load_tasks()}
    ids = cfg["task_ids"]
    if not ids or len(ids) != len(set(ids)) or set(ids) - tasks.keys():
        raise ValueError("explicit unique existing task_ids required")
    manifest = {"benchmark": "workbench", "domain": "multi_domain", "tasks_version": "v1",
                "manta_commit": PIN, "task_ids": ids, "assets_sha256": hashes,
                "models": {k: {"model": v["model"], "base_url": v["base_url"],
                               "temperature": v.get("temperature")}
                           for k, v in cfg["models"].items()}, "runtime": cfg["runtime"],
                "scoring": "pinned MANTA WorkBench state-change evaluator", "model_requests": 0}
    root = Path(__file__).resolve().parents[1]
    manifest["calc_source_sha256"] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in
        ["src/calc/adaptive.py", "src/calc/progress.py", "src/calc/llm.py", "scripts/run_adaptive_workbench.py"]}
    manifest["skills"] = cfg.get("skills", {})
    manifest["allowed_initial_operations"] = sorted(allowed_operations(mode, True, True))
    manifest["allowed_later_operations"] = sorted(allowed_operations(mode, False, True))
    if not args.execute:
        # Exercise the real evaluator with an empty prediction, not a fake success.
        first = tasks[ids[0]]
        evaluation = benchmark.evaluate(first, "", run_metadata={"function_calls": [], "error": "preflight_only"})
        print(json.dumps({"preflight": "passed", "available_tasks": len(tasks),
                          "empty_attempt_success": evaluation.success, **manifest}, indent=2))
        return 0
    clients = {}
    for tier in ("strong", "weak"):
        spec = cfg["models"][tier]
        if not spec["model"] or spec["model"].startswith("SET_"):
            raise ValueError(f"configure actual {tier} model ID before execute")
        key = os.environ.get(spec["key_env"])
        if not key:
            raise ValueError(f"missing credential environment variable for {tier}")
        clients[tier] = OpenAICompatibleClient(spec["base_url"], spec["model"], key,
                                              temperature=spec.get("temperature"))
    output = Path(cfg["output_dir"]) / mode
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summaries = []
    try:
        for task_id in ids:
            task = tasks[task_id]
            sandbox = sandbox_type(Path(cfg["data_dir"]))
            tools = benchmark._build_tools(sandbox, list(task.metadata["domains"]))
            mapping = {t["name"].replace(".", "__"): t for t in tools}
            schemas = [{"type": "function", "function": {"name": name, "description": t["description"],
                        "parameters": t["parameters"]}} for name, t in mapping.items()]
            actions = []

            def invoke(name, arguments):
                tool = mapping[name]
                actions.append(format_call(tool["name"], arguments))
                return tool["handler"](arguments)

            task_dir = output / task_id
            task_dir.mkdir()
            with (task_dir / "trace.jsonl").open("w", encoding="utf-8") as trace:
                def emit(event):
                    trace.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                    trace.flush()

                runtime = AdaptiveRuntime(strong=clients["strong"], weak=clients["weak"], tools=schemas,
                    invoke=invoke, skills=cfg.get("skills", {}), event_sink=emit,
                    environment_context=CONTEXT, **cfg["runtime"])
                # Only task text is passed, never metadata.answer or templates.
                try:
                    result = runtime.run(str(task.prompt))
                except Exception as exc:
                    from calc.llm import aggregate_usage
                    result = {"answer": "", "status": "runtime_error", "error_type": type(exc).__name__,
                              "calls": runtime.calls, "events": runtime.events,
                              "usage": aggregate_usage(runtime.calls), "correctness": "not_evaluated"}
            evaluation = benchmark.evaluate(task, result["answer"],
                run_metadata={"function_calls": actions, "error": ""})
            # Preserve native state score separately from completion; do not redefine correctness.
            row = {"task_id": task_id, "completion": result["status"] == "answered",
                   "success": evaluation.success, "status": result["status"], "usage": result["usage"],
                   "metrics": result.get("metrics"), "elapsed_seconds": result.get("elapsed_seconds")}
            (task_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            (task_dir / "evaluation.json").write_text(json.dumps(asdict(evaluation), ensure_ascii=False, indent=2), encoding="utf-8")
            summaries.append(row)
            (output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
            if result["status"] == "runtime_error":
                break  # retain failure and spent usage; do not automatically repeat paid work
    finally:
        for client in clients.values():
            client.close()
    print(json.dumps({"output_dir": str(output), "tasks": summaries}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
