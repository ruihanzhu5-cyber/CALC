"""Package public BCP questions as Harbor tasks; gold fields are never copied."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from . import bcp_tools

DOCKERFILE = """FROM python:3.12-slim-bookworm
WORKDIR /workspace
COPY bcp_tools.py /opt/bcp_tools.py
RUN printf '#!/bin/sh\\nexec python3 /opt/bcp_tools.py search "$@"\\n' > /usr/local/bin/search \\
 && printf '#!/bin/sh\\nexec python3 /opt/bcp_tools.py get_document "$@"\\n' > /usr/local/bin/get_document \\
 && chmod +x /usr/local/bin/search /usr/local/bin/get_document \\
 && mkdir -p /logs/agent /logs/verifier
CMD ["sh", "-c", "sleep infinity"]
"""

COMPOSE = """services:
  main:
    build:
      context: .
      dockerfile: Dockerfile
    image: ${MAIN_IMAGE_NAME}
    network_mode: host
    command: ["sh", "-c", "sleep infinity"]
    environment:
      BCP_BASE_URL: "${BCP_BASE_URL:-http://127.0.0.1:8765}"
      BCP_TOOL_LOG: /logs/agent/bcp_tools.jsonl
"""

TASK_TOML = """version = "1.0"

[metadata]
benchmark = "BrowseComp-Plus"
adapter = "CALC shared gateway port of official CLM"
evaluation = "external_official_judge_required"

[agent]
timeout_sec = 7200

[verifier]
timeout_sec = 30

[environment]
build_timeout_sec = 600
cpus = 1
memory_mb = 1024
workdir = "/workspace"
network_mode = "public"
"""

INSTRUCTION = """# Frozen-corpus research question

{query}

Use only the frozen corpus provided by the following commands for research evidence:
- `search "a precise search query"`
- `get_document "DOCID"`

Both commands call the same shared BCP gateway as the other evaluated agents.
Search returns the gateway's top-10 capped snippets; the reader returns the gateway's
document view with its shared cap. Do not fetch external web pages or change tool scripts.

Use the official CLM context file and editing instructions in your system prompt.
Write your final response to `/workspace/answer.txt` in this format:

Explanation: evidence-grounded explanation citing document IDs in square brackets.
Exact Answer: succinct answer
Confidence: 0% to 100%

When the answer file is ready, submit using the standalone command:
`echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`

The local Harbor verifier exports answer artifacts only. It does not grade correctness;
official BCP evaluation runs separately on the host. No gold answers are in this task.
"""

VERIFY_SH = """#!/bin/sh
set -eu
mkdir -p /logs/verifier
if [ -f /workspace/answer.txt ]; then
  cp /workspace/answer.txt /logs/verifier/answer.txt
fi
printf '{"evaluation":"not_run","correctness_score":null}\\n' > /logs/verifier/evaluation.json
# An empty reward map is valid Harbor output and contains no correctness score.
printf '{}\\n' > /logs/verifier/reward.json
"""


def selected_tasks(path: Path, task_ids: list[str] | None, limit: int | None) -> list[dict[str, str]]:
    selected = None if task_ids is None else set(task_ids)
    seen: set[str] = set()
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("query"), str) or not row["query"].strip():
            raise ValueError(f"line {number}: query must be a nonempty string")
        query_id = str(row["query_id"])
        if query_id in seen:
            raise ValueError(f"duplicate task ID: {query_id}")
        seen.add(query_id)
        if selected is None or query_id in selected:
            result.append({"query_id": query_id, "query": row["query"]})
    if selected is not None and selected - seen:
        raise ValueError(f"unknown task IDs: {sorted(selected - seen)}")
    return result if limit is None else result[:limit]


def pack(source: Path, output: Path, task_ids: list[str] | None = None, limit: int | None = None) -> dict:
    rows = selected_tasks(source, task_ids, limit)
    output.mkdir(parents=True, exist_ok=True)
    planned = []
    for row in rows:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", row["query_id"])[:60] or "query"
        name = "bcp-" + safe + "-" + hashlib.sha256(row["query_id"].encode()).hexdigest()[:8]
        target = output / name
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite task: {target}")
        planned.append((row, target))
    manifest = {"benchmark": "BrowseComp-Plus", "evaluation": "not_run", "tasks": []}
    for row, target in planned:
        environment, tests = target / "environment", target / "tests"
        environment.mkdir(parents=True)
        tests.mkdir()
        (target / "instruction.md").write_text(INSTRUCTION.format(query=row["query"]), encoding="utf-8", newline="\n")
        (target / "task.toml").write_text(TASK_TOML, encoding="utf-8", newline="\n")
        (target / "query.json").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        (environment / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8", newline="\n")
        (environment / "docker-compose.yaml").write_text(COMPOSE, encoding="utf-8", newline="\n")
        shutil.copyfile(Path(bcp_tools.__file__), environment / "bcp_tools.py")
        (tests / "test.sh").write_text(VERIFY_SH, encoding="utf-8", newline="\n")
        manifest["tasks"].append({"query_id": row["query_id"], "directory": target.name})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--task-ids", type=Path, dest="ids_file", help="JSON list or object with task_ids list")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    ids = args.task_ids
    if args.task_ids is not None and args.task_ids == []:
        raise ValueError("Task selection must be nonempty")
    # The file option has a distinct argparse destination to avoid hidden selection changes.
    file_path = getattr(args, "ids_file", None)
    if file_path:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        ids = raw.get("task_ids") if isinstance(raw, dict) else raw
        if not isinstance(ids, list) or not ids or not all(isinstance(value, (str, int)) for value in ids):
            parser.error("--task-ids must contain a nonempty list of task IDs")
        ids = [str(value) for value in ids]
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    print(json.dumps(pack(args.tasks, args.output, ids, args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
