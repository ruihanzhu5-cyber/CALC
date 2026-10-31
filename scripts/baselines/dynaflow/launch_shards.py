"""Default dry-run launcher for prepared DynaFlow shards. No judge is invoked."""
import json
import os
import subprocess
from argparse import ArgumentParser
from pathlib import Path


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--query-id", action="append", help="Repeat to select a subset; default all prepared tasks")
    parser.add_argument("--execute", action="store_true", help="Explicitly launch paid model requests; default prints commands only")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    wanted = set(args.query_id or [])
    rows = [row for row in manifest["shards"] if not wanted or row["query_id"] in wanted]
    if wanted - {row["query_id"] for row in rows}:
        raise ValueError("unknown query ID")
    if not args.execute:
        print(json.dumps({"dry_run": True, "model_calls": 0, "commands": [row["run_command"] for row in rows]}, indent=2))
        return
    if not os.environ.get("CALC_GATEWAY_KEY"):
        raise ValueError("CALC_GATEWAY_KEY must be injected by the common WSL launcher")
    for row in rows:
        # The native runner retains its own resumable results and usage logs.
        subprocess.run(row["run_command"], check=True)


if __name__ == "__main__":
    main()
