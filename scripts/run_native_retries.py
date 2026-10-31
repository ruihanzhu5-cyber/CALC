"""Retry only missing submissions under author settings; retain judged answers.

Defaults to preparation only. Uses public questions, never reference answers.
"""
import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil

import httpx

from export_pilot import convert
from run_first20 import METHODS, commands, interrupt_queue, retrieval_preflight, run_wave, write_json


def select_retries(source: Path, query_ids: list[str]):
    retained, retry = [], []
    for method in METHODS:
        summary = json.loads((source / "evals" / method / "evaluation_summary.json").read_text(encoding="utf-8-sig"))
        if summary["evaluation"] != "complete" or summary["num_judge_errors"] != 0:
            raise ValueError("Source scoring must be complete before selecting missing submissions")
        for qid in query_ids:
            evaluation_path = source / "evals" / method / f"run_{qid}_eval.json"
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8-sig"))
            row = {"method": method, "query_id": qid, "source_eval": str(evaluation_path),
                   "source_eval_sha256": hashlib.sha256(evaluation_path.read_bytes()).hexdigest()}
            if evaluation["status"] == "judged":
                # Keep complete submissions even when incorrect. No answer-based selection.
                retained.append(row)
            elif evaluation["status"] == "incomplete_agent_response":
                retry.append(row)
            else:
                raise ValueError(f"Unexpected source evaluation state: {evaluation['status']}")
    return retained, retry


def retain_recovery_submissions(root: Path, recovery_tag: str, retained: list, retry: list):
    """Keep any completed, scored submission from an interrupted attempt, even wrong."""
    recovery = root / "runs" / recovery_tag
    remaining = []
    for row in retry:
        method, qid = row["method"], row["query_id"]
        try:
            native, _ = convert(root, recovery, recovery_tag, method, qid)
        except (FileNotFoundError, KeyError):
            native = None
        texts = [item.get("output", "") for item in (native or {}).get("result", [])]
        raw_tool_protocol = any("<｜｜DSML｜｜" in text for text in texts)
        if native and native["status"] == "completed" and native["result"] and not raw_tool_protocol:
            path = recovery / "evals" / method / f"run_{qid}_eval.json"
            evaluation = json.loads(path.read_text(encoding="utf-8-sig"))
            if evaluation["status"] != "judged":
                raise ValueError(f"Score the retained submission first: {method}/{qid}")
            retained.append({"method": method, "query_id": qid, "source_eval": str(path),
                             "source_eval_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "retained_from_recovery": recovery_tag})
        else:
            remaining.append(row)
    return retained, remaining


def use_prebuilt_clm_task(root: Path, run_tag: str, job: dict, image: str):
    """Copy public task inputs; use the identical prebuilt environment via Harbor."""
    index = 2  # bash, run_clm_bcp.sh, HARBOR_TASK_DIRECTORY
    source = Path(job["command"][index])
    target = root / "runs" / run_tag / "clm-tasks" / source.name
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target)
    config = target / "task.toml"
    text = config.read_text()
    text = text.replace("[environment]\n", f'[environment]\ndocker_image = "{image}"\n', 1)
    config.write_text(text)
    compose = target / "environment/docker-compose.yaml"
    text = compose.read_text().replace("    build:\n      context: .\n      dockerfile: Dockerfile\n", "")
    compose.write_text(text.replace("${MAIN_IMAGE_NAME}", "${PREBUILT_IMAGE_NAME}"))
    job["command"][index] = str(target)


def make_job(root: Path, run_tag: str, row: dict, task: dict):
    method, qid = row["method"], row["query_id"]
    output = root / "runs" / run_tag / method / qid
    command, env = commands(root, method, task, output, 0, run_tag, 4096)
    env["CALC_TRANSPORT_ATTEMPTS"] = "3"
    if method in {"main", "joint"}:
        path = root / "configs" / run_tag / method / f"{qid}.json"
        config = json.loads(path.read_text())
        config["llm"]["timeout"] = 600
        config["run"].update(max_model_requests=0, max_total_tokens=0, finalize_on_limit=True,
                             transport_attempts=3,
                             run_kind="native_settings_missing_submission_retry")
        write_json(path, config)
    elif method == "porchestra":
        # Match the public GAIA runner: attempts*4+1 Main decisions; delegate
        # default 500 total steps, sessions of 30. Paper's 300-step setting is
        # recorded separately in the audit, not substituted silently.
        for flag, value in [("--max-main-decisions", "41"), ("--max-subagent-steps", "500"),
                            ("--max-tool-calls", "0")]:
            command[command.index(flag) + 1] = value
    elif method == "clm":
        # Published bcp.yaml: max_steps=500; native default LM cap=2*500+24.
        env["CALC_CLM_CALL_CAP"] = "1024"
        env["CALC_MAX_OUTPUT_TOKENS"] = "4096"
    return {"key": f"{method}/{qid}", "method": method, "output": output, "command": command, "env": env}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/mnt/d/CALC-experiments"))
    parser.add_argument("--source-run", default="dev5-flash-1m-par3-v1")
    parser.add_argument("--run-tag", default="dev5-native-retry19-v2")
    parser.add_argument("--concurrency", type=int, default=19)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recovery-run", help="Interrupted prior attempt; retain its complete scored submissions")
    parser.add_argument("--clm-prebuilt-image", help="Identical environment image built before concurrent actors")
    parser.add_argument("--only-task", action="append", help="Explicit method/query_id subset; defer all others")
    args = parser.parse_args()
    import re
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in (args.source_run, args.run_tag)):
        raise ValueError("Use safe, distinct run tags")
    if args.run_tag == args.source_run or args.concurrency < 1:
        raise ValueError("A fresh run tag and positive concurrency are required")
    source = args.root / "runs" / args.source_run
    run = args.root / "runs" / args.run_tag
    if (run / "queue.json").exists():
        raise ValueError("Run already launched; do not duplicate paid retries")
    task_path = args.root / "bench/browsecomp-plus/tasks/first20.dev.jsonl"
    tasks = [json.loads(line) for line in task_path.read_text().splitlines() if line.strip()][:5]
    if any(set(task) != {"query_id", "query"} for task in tasks):
        raise ValueError("Actor input must contain only public question fields")
    by_id = {str(task["query_id"]): task for task in tasks}
    retained, retry = select_retries(source, list(by_id))
    if args.recovery_run:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.recovery_run) or args.recovery_run == args.run_tag:
            raise ValueError("Use a distinct safe recovery run tag")
        retained, retry = retain_recovery_submissions(args.root, args.recovery_run, retained, retry)
    deferred = []
    if args.only_task:
        available = {f"{row['method']}/{row['query_id']}" for row in retry}
        if not set(args.only_task) <= available:
            raise ValueError("Requested subset must consist of missing submissions")
        deferred = [row for row in retry if f"{row['method']}/{row['query_id']}" not in args.only_task]
        retry = [row for row in retry if f"{row['method']}/{row['query_id']}" in args.only_task]
    jobs = [make_job(args.root, args.run_tag, row, by_id[row["query_id"]]) for row in retry]
    if args.clm_prebuilt_image:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.clm_prebuilt_image):
            raise ValueError("Pin the prebuilt image by its immutable local image ID")
        for job in jobs:
            if job["method"] == "clm":
                use_prebuilt_clm_task(args.root, args.run_tag, job, args.clm_prebuilt_image)
    manifest = {"run_tag": args.run_tag, "source_run": args.source_run,
                "created_at": datetime.now(UTC).isoformat(), "retained": retained, "retry": retry,
                "retained_count": len(retained), "retry_count": len(retry),
                "selection": "evaluation status only; incorrect submitted answers are retained",
                "episode_concurrency": args.concurrency, "gateway_mode": "native_passthrough",
                "aggregate_token_limit": None, "external_model_request_limit": None,
                "native_settings": {
                    "porchestra": {"main_decisions": 41, "subagent_steps": 500, "session_steps": 30,
                                   "max_attempts": 10, "output_tokens": "not specified by native caller"},
                    "clm": {"task_steps": 500, "lm_call_cap": 1024, "output_tokens": 4096,
                            "context_budget": 28672, "reserve": 2048, "rollback_retries": 6, "finalize_nudge_turns": 3},
                    "dynaflow": {"output_tokens": 65536, "question_deadline": None,
                                 "workflow_token_budget": None, "source": "published configs/dynamic.json"},
                    "main_joint": {"task_steps": 100, "output_tokens": 4096, "model_input_budget": 32768,
                                   "origin": "own runtime; no author default; submission turns enabled"}},
                "comparison_scope": "diagnostic retry cohort, not a fresh paired algorithm comparison"}
    manifest.update(recovery_run=args.recovery_run, clm_prebuilt_image=args.clm_prebuilt_image,
                    deferred=deferred, deferred_count=len(deferred),
                    prior_attempt_costs="All prior model-calls logs remain chargeable; never replaced or reset")
    write_json(run / "retry_manifest.json", manifest)
    if not args.execute:
        print(json.dumps({"prepared": True, "retained": retained, "retry": retry,
                          "paid_calls": 0, "concurrency": args.concurrency}))
        return 0
    if not os.environ.get("CALC_GATEWAY_KEY"):
        raise ValueError("Launch with invoke_wsl_experiment.ps1")
    with httpx.Client(timeout=15, trust_env=False) as client:
        health = client.get("http://127.0.0.1:8767/health").raise_for_status().json()
        if health.get("mode") != "native_passthrough" or health["max_in_flight_model_requests"] < args.concurrency:
            raise ValueError("Start a native-settings gateway with sufficient concurrency")
        client.get("http://127.0.0.1:8766/ready").raise_for_status()
    retrieval_preflight(tasks[0])
    state = {"kind": "missing_submission_retry", "run_tag": args.run_tag, "source_run": args.source_run,
             "methods": list(METHODS), "query_ids": list(by_id), "concurrency": args.concurrency,
             "token_stop_threshold": None, "max_model_requests": None, "evaluation": "not_run", "jobs": {}}
    state.update(scheduler_pid=os.getpid(), boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip())
    write_json(run / "queue.json", state)
    previous = signal.signal(signal.SIGTERM, interrupt_queue)
    try:
        code = run_wave(jobs, state, run / "queue.json", args.concurrency, fail_fast=False)
        state["status"] = "actors_complete" if code == 0 else "actor_process_error"
        write_json(run / "queue.json", state)
        return code
    except KeyboardInterrupt:
        state.update(status="interrupted", stopped_at=datetime.now(UTC).isoformat())
        write_json(run / "queue.json", state)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
