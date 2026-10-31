"""Prepare native one-question DynaFlow runs, never execute model calls.

Per-question gateway path and authentication environment apply to both main and
workers. CALC_GATEWAY_KEY is not read or saved by this preparation script.
"""
import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import quote

import dynaflow
from dynaflow.data import prepare, verify
from prepare_inputs import config, questions


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gateway", default="http://127.0.0.1:8767")
    parser.add_argument("--max-output", type=int, default=4096)
    parser.add_argument("--deadline", type=int, default=1200)
    args = parser.parse_args()
    rows = questions(args.tasks)
    if args.out.exists():
        raise ValueError("output exists; choose a new immutable preparation directory")
    if args.max_output <= 0 or args.deadline <= 0:
        raise ValueError("positive max-output/deadline required")
    args.out.mkdir(parents=True)
    shards = []
    for position, row in enumerate(rows, 1):
        qid = row["task_id"]
        if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in qid):
            raise ValueError("query_id must be a safe stable path component")
        shard = args.out / qid
        inputs = shard / "inputs"
        inputs.mkdir(parents=True)
        task = {**row, "number": 1}
        endpoint = args.gateway.rstrip("/") + "/v1/dynaflow/" + quote(qid, safe="")
        cfg = config(args.max_output, args.deadline, endpoint)
        for name, value in [("questions.json", [task]), ("config.json", cfg)]:
            (inputs / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run_dir = shard / "run"
        prepare(run_dir, inputs / "questions.json", inputs / "config.json", profile="dynamic")
        verify(run_dir)
        shards.append({"position": position, "query_id": qid, "run_dir": str(run_dir), "gateway_base_url": endpoint,
                       "run_command": ["env", "PYTHONDONTWRITEBYTECODE=1",
                                       "PYTHONPATH=" + str(Path(dynaflow.__file__).resolve().parent.parent),
                                       sys.executable, "-m", "dynaflow", "run", str(run_dir)]})
    manifest = {"method": "DynaFlow-Base-Dynamic-common-backbone-port", "shards": shards,
                "model_calls": 0, "auth_env": "CALC_GATEWAY_KEY", "native_model_preflight_per_shard": True,
                "upstream_commit": "7451639d197ef844b4157cf40eadac68e9eba8ca",
                "node_image": "node:24.14.0-bookworm-slim",
                "node_image_digest": "sha256:d8e448a56fc63242f70026718378bd4b00f8c82e78d20eefb199224a4d8e33d8",
                "note": "Each run's native preflight makes a diagnostic model call when eventually executed. Gateway accounts and serializes all main/worker requests."}
    (args.out / "shards.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prepared_shards": len(shards), "verified": True, "model_calls": 0, "manifest": str(args.out / "shards.json")}))


if __name__ == "__main__":
    main()
