"""Run the frozen BC+ development pilot: baselines first, then CALC V0.

Dry-run by default. Run inside CALC-Research using invoke_wsl_experiment.ps1
to receive only the local gateway token. No gold answers or judge are loaded.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import httpx


ROOT = Path("/mnt/d/CALC-experiments")
METHODS = ("main", "porchestra", "clm", "dynaflow", "joint")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def commands(root: Path, method: str, task: dict, output: Path,
             token_limit: int = 160000, run_tag: str = "first20-flash-v2",
             max_output: int = 4096) -> tuple[list[str], dict[str, str]]:
    qid = str(task["query_id"])
    python = "/opt/calc/envs/calc/bin/python"
    base = f"http://127.0.0.1:8767/v1/{run_tag}-{method}/{qid}"
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env["CALC_MAX_OUTPUT_TOKENS"] = str(max_output)
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1,host.docker.internal"
    env["TMPDIR"] = "/opt/calc/tmp"
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    if method in {"main", "joint"}:
        config = {
            "tasks_path": str(root / "bench/browsecomp-plus/tasks/first20.dev.jsonl"),
            "task_ids": [qid], "output_dir": str(output),
            "llm": {"base_url": base, "model": "deepseek-flash", "api_key_env": "CALC_GATEWAY_KEY",
                    "timeout": 300, "reasoning_effort": "high", "extra_body": {"thinking": {"type": "enabled"}}},
            "retriever": {"base_url": "http://127.0.0.1:8765", "timeout": 60},
            "run": {"mode": method, "run_kind": "development_first20", "main_max_steps": 100,
                    "worker_max_steps": 6, "max_model_requests": 100, "max_output_tokens": max_output,
                    "context_budget": 8192, "main_context_budget": 28672, "controller_interval": 3,
                    "main_history_mode": "raw", "model_input_budget": 32768, "max_total_tokens": token_limit},
        }
        config_path = root / "configs" / run_tag / method / f"{qid}.json"
        write_json(config_path, config)
        return [python, "-m", "calc.cli", "run-browsecomp", "--config", str(config_path)], env
    if method == "porchestra":
        return ["/opt/calc/envs/porchestra/bin/python", str(root / "code/CALC/scripts/baselines/porchestra/porchestra_bcp.py"),
                "--tasks", str(root / "bench/browsecomp-plus/tasks/first20.dev.jsonl"),
                "--query-id", qid, "--output-dir", str(output), "--model", "deepseek-flash",
                "--llm-proxy", base.rsplit("/", 1)[0], "--max-main-decisions", "100",
                "--max-tool-calls", "200", "--max-subagent-steps", "100"], env
    if method == "clm":
        port = root / "upstreams/CLM/calc_port"
        manifest = json.loads((port / "tasks_first20/manifest.json").read_text())
        row = next(row for row in manifest["tasks"] if str(row["query_id"]) == qid)
        env["CLM_API_BASE"] = base
        env["CLM_TRIALS_DIR"] = str(root / "runs" / run_tag / "clm-native")
        return ["bash", str(root / "code/CALC/scripts/baselines/clm/run_clm_bcp.sh"),
                str(port / "tasks_first20" / row["directory"]),
                "--trial-name", f"{run_tag}-clm-{qid}"], env
    manifest_path = root / "runs" / run_tag / "dynaflow-prepared/shards.json"
    if run_tag == "first20-flash-v2":
        manifest_path = root / "runs/dynaflow-flash-first20-prepared/shards.json"
    manifest = json.loads(manifest_path.read_text())
    row = next(row for row in manifest["shards"] if str(row["query_id"]) == qid)
    # The author-prepared, per-task config already names /v1/dynaflow/<qid>.
    command = [part.replace("/mnt/d/CALC-experiments/envs/calc-linux/bin/python", python)
               for part in row["run_command"]]
    return command, env


def run_wave(jobs: list[dict], state: dict, state_path: Path, concurrency: int, *, fail_fast: bool = True) -> int:
    """Single-writer scheduler; each episode owns its process group and log."""
    active: list[tuple] = []
    pending = iter(jobs)
    exhausted = False
    exit_code = 0
    last_heartbeat = 0.0
    try:
        while active or not exhausted:
            # Observe failures before launching replacements.
            for entry in list(active):
                process, log, key, output = entry
                code = process.poll()
                if code is None:
                    continue
                log.close()
                active.remove(entry)
                if key.split("/", 1)[0] in {"main", "joint"} and code == 0 and not (output / "summary.json").is_file():
                    code = 2
                state["jobs"][key].update(status="process_completed" if code == 0 else "process_error",
                                          returncode=code, finished_at=datetime.now(UTC).isoformat())
                write_json(state_path, state)
                print(f"END {key}: {state['jobs'][key]['status']}", flush=True)
                if code and fail_fast:
                    return code
                exit_code = exit_code or code
            while len(active) < concurrency and not exhausted:
                spec = next(pending, None)
                if spec is None:
                    exhausted = True
                    break
                key, output = spec["key"], spec["output"]
                output.mkdir(parents=True, exist_ok=True)
                job = {"status": "running", "started_at": datetime.now(UTC).isoformat(),
                       "command": spec["command"], "output_dir": str(output)}
                if spec["method"] == "dynaflow":
                    job["native_run_dir"] = spec["command"][-1]
                state["jobs"][key] = job
                write_json(state_path, state)
                log = (output / "process.log").open("w", encoding="utf-8")
                try:
                    process = subprocess.Popen(spec["command"], env=spec["env"], stdout=log,
                                               stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
                except OSError:
                    log.close()
                    job.update(status="process_error", error_type="process_start_failed",
                               finished_at=datetime.now(UTC).isoformat())
                    write_json(state_path, state)
                    raise
                job["pid"] = process.pid
                active.append((process, log, key, output))
                write_json(state_path, state)
                print(f"START {key}", flush=True)
            if active:
                if time.monotonic() - last_heartbeat >= 5:
                    state["heartbeat_at"] = datetime.now(UTC).isoformat()
                    write_json(state_path, state)
                    last_heartbeat = time.monotonic()
                time.sleep(0.1)
    finally:
        # SIGINT/SIGTERM or a failed sibling must not leave paid workers alive.
        for process, _log, _key, _output in active:
            if process.poll() is None:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    process.terminate()
        for process, log, key, _output in active:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
            log.close()
            state["jobs"][key].update(status="interrupted", returncode=process.returncode,
                                      finished_at=datetime.now(UTC).isoformat())
        if active:
            write_json(state_path, state)
    return exit_code


def retrieval_preflight(task: dict) -> None:
    # Health alone missed a wedged retriever in dev5. Exercise both real tool
    # paths before starting any model requests; no labels or LLM are needed.
    with httpx.Client(trust_env=False, timeout=15) as client:
        response = client.post("http://127.0.0.1:8765/retrieve", json={"query": task["query"]})
        response.raise_for_status()
        rows = response.json()["result"]
        if not rows:
            raise RuntimeError("Retrieval preflight returned no documents")
        response = client.post("http://127.0.0.1:8765/document", json={"docid": rows[0]["docid"]})
        response.raise_for_status()
        if not response.json().get("document"):
            raise RuntimeError("Document-reader preflight returned no document")


def interrupt_queue(*_args) -> None:
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Concurrent independent episodes within each method; default 1")
    parser.add_argument("--token-limit", type=int, default=160000)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--run-tag", default="first20-flash-v2")
    parser.add_argument("--after-sanity", action="store_true",
                        help="Wait for the active one-task-per-method checks before expanding to 20")
    args = parser.parse_args()
    if min(args.concurrency, args.max_output_tokens) < 1:
        raise ValueError("concurrency and max-output-tokens must be positive")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run_tag):
        raise ValueError("run-tag must be a directory-safe identifier")
    task_file = args.root / "bench/browsecomp-plus/tasks/first20.dev.jsonl"
    tasks = [json.loads(line) for line in task_file.read_text().splitlines() if line.strip()][:args.limit]
    if not 1 <= args.limit <= 20 or not tasks:
        raise ValueError("Pilot limit must be between 1 and 20")
    if any(set(task) != {"query_id", "query"} for task in tasks):
        raise ValueError("Pilot input must contain only public query fields")
    queue_root = args.root / "runs" / args.run_tag
    queue_root.mkdir(parents=True, exist_ok=True)
    state_path = queue_root / "queue.json"
    if args.after_sanity:
        if not args.execute:
            raise ValueError("--after-sanity requires --execute")
        first_id = str(tasks[0]["query_id"])
        deadline = time.monotonic() + 3600
        while True:
            snapshot = json.loads(state_path.read_text()) if state_path.exists() else {"jobs": {}}
            sanity = [snapshot["jobs"].get(f"{method}/{first_id}", {}) for method in METHODS]
            if any(job.get("status") == "process_error" for job in sanity):
                raise RuntimeError("A sanity process failed; fix its setup before expanding the paid queue")
            if all(job.get("status") == "process_completed" for job in sanity):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Sanity queue did not finish; inspect queue.json")
            time.sleep(5)
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "kind": "development_pilot", "model": "deepseek-flash", "evaluation": "not_run",
        "run_tag": args.run_tag, "token_stop_threshold": args.token_limit,
        "query_ids": [str(task["query_id"]) for task in tasks], "methods": args.methods,
        "task_file_sha256": hashlib.sha256(task_file.read_bytes()).hexdigest(), "jobs": {},
    }
    waves = []
    for method in args.methods:
        wave = []
        for task in tasks:
            qid = str(task["query_id"])
            key = f"{method}/{qid}"
            output = queue_root / method / qid
            command, env = commands(args.root, method, task, output, args.token_limit, args.run_tag,
                                    args.max_output_tokens)
            if not args.execute:
                print(json.dumps({"dry_run": True, "job": key, "command": command,
                                  "concurrency": args.concurrency}))
                continue
            previous = state["jobs"].get(key)
            if previous and previous["status"] == "process_completed":
                continue
            if previous:
                raise RuntimeError(f"Inspect incomplete job {key} before rerunning; no automatic paid retry")
            wave.append({"key": key, "method": method, "output": output, "command": command, "env": env})
        waves.append(wave)
    if not args.execute:
        return 0
    if state.get("status") == "stopped_by_user":
        raise RuntimeError("This run was stopped by the user; choose a new run tag")
    state["concurrency"] = args.concurrency
    state["max_output_tokens"] = args.max_output_tokens
    if args.execute:
        if not os.environ.get("CALC_GATEWAY_KEY"):
            raise ValueError("Use invoke_wsl_experiment.ps1 to inject CALC_GATEWAY_KEY")
        for port in (8765, 8767):
            with httpx.Client(trust_env=False, timeout=15) as client:
                health = client.get(f"http://127.0.0.1:{port}/health")
                health.raise_for_status()
                if port == 8767:
                    if health.json()["observed_token_stop_threshold"] != args.token_limit:
                        raise ValueError("Freeze the same token limit in the gateway and every pilot method before batching")
                    if health.json()["max_in_flight_model_requests"] < args.concurrency:
                        raise ValueError("Gateway concurrency must be at least the episode concurrency")
                    if health.json().get("max_output_tokens", 4096) != args.max_output_tokens:
                        raise ValueError("Freeze the same output token limit in the gateway and every pilot method")
        retrieval_preflight(tasks[0])
        if "dynaflow" in args.methods:
            with httpx.Client(trust_env=False, timeout=15) as client:
                client.get("http://127.0.0.1:8766/ready").raise_for_status()
    previous_handler = signal.signal(signal.SIGTERM, interrupt_queue)
    try:
        for wave in waves:
            code = run_wave(wave, state, state_path, args.concurrency)
            if code:
                return code
    except KeyboardInterrupt:
        state.update(status="interrupted", stopped_at=datetime.now(UTC).isoformat())
        write_json(state_path, state)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
