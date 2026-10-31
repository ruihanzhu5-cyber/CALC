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
import subprocess
import sys

import httpx


ROOT = Path("/mnt/d/CALC-experiments")
METHODS = ("main", "porchestra", "clm", "dynaflow", "joint")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def commands(root: Path, method: str, task: dict, output: Path) -> tuple[list[str], dict[str, str]]:
    qid = str(task["query_id"])
    python = "/opt/calc/envs/calc/bin/python"
    base = f"http://127.0.0.1:8767/v1/first20-{method}-v2/{qid}"
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
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
                    "worker_max_steps": 6, "max_model_requests": 100, "max_output_tokens": 4096,
                    "context_budget": 8192, "main_context_budget": 28672, "controller_interval": 3,
                    "main_history_mode": "raw", "model_input_budget": 32768, "max_total_tokens": 160000},
        }
        config_path = root / "configs/first20" / method / f"{qid}.json"
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
        env["CLM_TRIALS_DIR"] = str(root / "runs/first20-flash-v2/clm-native")
        return ["bash", str(root / "code/CALC/scripts/baselines/clm/run_clm_bcp.sh"),
                str(port / "tasks_first20" / row["directory"]),
                "--trial-name", f"first20-clm-v2-{qid}"], env
    manifest = json.loads((root / "runs/dynaflow-flash-first20-prepared/shards.json").read_text())
    row = next(row for row in manifest["shards"] if str(row["query_id"]) == qid)
    # The author-prepared, per-task config already names /v1/dynaflow/<qid>.
    command = [part.replace("/mnt/d/CALC-experiments/envs/calc-linux/bin/python", python)
               for part in row["run_command"]]
    return command, env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    task_file = args.root / "bench/browsecomp-plus/tasks/first20.dev.jsonl"
    tasks = [json.loads(line) for line in task_file.read_text().splitlines() if line.strip()][:args.limit]
    if not 1 <= args.limit <= 20 or not tasks:
        raise ValueError("Pilot limit must be between 1 and 20")
    if any(set(task) != {"query_id", "query"} for task in tasks):
        raise ValueError("Pilot input must contain only public query fields")
    queue_root = args.root / "runs/first20-flash-v2"
    queue_root.mkdir(parents=True, exist_ok=True)
    state_path = queue_root / "queue.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "kind": "development_first20", "model": "deepseek-flash", "evaluation": "not_run",
        "task_file_sha256": hashlib.sha256(task_file.read_bytes()).hexdigest(), "jobs": {},
    }
    if args.execute:
        if not os.environ.get("CALC_GATEWAY_KEY"):
            raise ValueError("Use invoke_wsl_experiment.ps1 to inject CALC_GATEWAY_KEY")
        for port in (8765, 8767):
            with httpx.Client(trust_env=False, timeout=15) as client:
                client.get(f"http://127.0.0.1:{port}/health").raise_for_status()
        if "dynaflow" in args.methods:
            with httpx.Client(trust_env=False, timeout=15) as client:
                client.get("http://127.0.0.1:8766/ready").raise_for_status()
    for method in args.methods:
        for task in tasks:
            qid = str(task["query_id"])
            key = f"{method}/{qid}"
            output = queue_root / method / qid
            command, env = commands(args.root, method, task, output)
            if not args.execute:
                print(json.dumps({"dry_run": True, "job": key, "command": command}))
                continue
            if state["jobs"].get(key, {}).get("status") == "process_completed":
                continue
            if key in state["jobs"]:
                raise RuntimeError(f"Inspect incomplete job {key} before rerunning; no automatic paid retry")
            output.mkdir(parents=True, exist_ok=True)
            job = {"status": "running", "started_at": datetime.now(UTC).isoformat(),
                   "command": command, "output_dir": str(output)}
            if method == "dynaflow":
                job["native_run_dir"] = str(args.root / "runs/dynaflow-flash-first20-prepared" / qid / "run")
            state["jobs"][key] = job
            write_json(state_path, state)
            print(f"START {key}", flush=True)
            with (output / "process.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            if method in {"main", "joint"} and result.returncode == 0 and not (output / "summary.json").is_file():
                result = subprocess.CompletedProcess(command, 2)
            job.update(status="process_completed" if result.returncode == 0 else "process_error",
                       returncode=result.returncode, finished_at=datetime.now(UTC).isoformat())
            write_json(state_path, state)
            print(f"END {key}: {job['status']}", flush=True)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
