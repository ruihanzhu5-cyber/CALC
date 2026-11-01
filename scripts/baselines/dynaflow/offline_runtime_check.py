"""Exercise native Docker/Node/RPC with an explicit local fixture, never an LLM.

This is an environment contract check, not a task trajectory or benchmark result.
"""
import json
import threading
from argparse import ArgumentParser
from pathlib import Path

from dynaflow.configuration import normalize
from dynaflow.workflow import Cancellation, Engine, check_runtime
from prepare_inputs import config


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("use a new check directory")
    cfg = normalize(config())
    runtime = check_runtime(cfg)
    calls = []

    def fixture(params, call_id, stop):
        calls.append({"params": params, "call_id": call_id})
        return {"kind": "ok", "output": "OFFLINE_FIXTURE_ONLY", "model": cfg["subagent_model"],
                "usage": {"outputTokens": 0}, "delivery": {"rawText": "OFFLINE_FIXTURE_ONLY", "deliveredOutput": "OFFLINE_FIXTURE_ONLY", "finishReason": "stop"}}

    invocation = {"script": "export const meta = {name:'offline-runtime-contract',description:'Local fixture; no model calls'}; return await agent('Environment contract fixture only', {allowedTools:['search','get_document']});", "maxConcurrency": 1}
    stop = Cancellation(threading.Event())
    result = Engine(args.out, "offline-fixture", invocation, cfg, fixture, stop).run()
    if result.get("status") != "completed" or result.get("returnValue") != "OFFLINE_FIXTURE_ONLY" or len(calls) != 1:
        raise RuntimeError("native engine fixture did not complete")
    (args.out / "environment-check.json").write_text(json.dumps({"check_type": "offline_fixture_not_benchmark", "runtime": runtime, "rpc_calls": calls, "model_calls": 0}, indent=2) + "\n")
    print(json.dumps({"status": "passed", "check_type": "offline_fixture_not_benchmark", "model_calls": 0, "runtime": runtime}))


if __name__ == "__main__":
    main()
