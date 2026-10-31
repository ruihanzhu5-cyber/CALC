"""Create answer-free native DynaFlow inputs/config, without API calls."""
import json
from argparse import ArgumentParser
from pathlib import Path

from bridge import TOOLS


def questions(source):
    rows, ids = [], set()
    for line in Path(source).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        # Strict allowlist: never forward labels, metadata, or qrels.
        task_id, query = value["query_id"], value["query"]
        if not isinstance(task_id, str) or not task_id or task_id in ids:
            raise ValueError("query_id must be a distinct nonempty string")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be nonempty")
        ids.add(task_id)
        rows.append({"number": len(rows) + 1, "dataset": "BrowseComp-Plus",
                     "task_id": task_id, "Question": query})
    if not rows:
        raise ValueError("no tasks")
    return rows


def config(max_output=4096, deadline=1200, base_url="http://127.0.0.1:8767/v1/dynaflow/unassigned"):
    return {
        "mode": "dynamic", "profile": "dynamic", "model": "deepseek-flash",
        "model_adapter": "deepseek", "api_key_env": "CALC_GATEWAY_KEY",
        "parameters": {"max_tokens": max_output, "thinking": True, "reasoning_effort": "high"},
        "seed": None, "seed_strategy": None, "extra_body": {},
        "servers": [{"id": "main", "url": base_url, "concurrency": 1}],
        "question_order": None, "question_deadline_seconds": deadline,
        "training_stage": "base-untrained-main-no-SFT-common-backbone-port",
        "subagent_model": "deepseek-flash", "subagent_adapter": "deepseek",
        "subagent_parameters": None, "subagent_extra_body": {},
        "workflow": {
            "backend": "portable", "engine_mode": "docker",
            "container_image": "node:24.14.0-bookworm-slim",
            "cloud_url": base_url, "cloud_key_env": "CALC_GATEWAY_KEY",
            "tools": TOOLS, "tool_service_url": "http://127.0.0.1:8766",
            "tool_key_env": "DYNAFLOW_TOOL_API_KEY",
            "research_environment": "Fixed BrowseComp-Plus BM25 corpus only. search returns top-10 snippets (512-token cap); get_document reads raw corpus documents (8192-token cap). No live web, filesystem or shell tools.",
        },
    }


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-output", type=int, default=4096)
    parser.add_argument("--deadline", type=int, default=1200)
    args = parser.parse_args()
    if args.max_output <= 0 or args.deadline <= 0:
        raise ValueError("positive output/deadline required")
    args.out.mkdir(parents=True, exist_ok=False)
    rows = questions(args.tasks)
    for name, value in [("questions.json", rows), ("config.json", config(args.max_output, args.deadline))]:
        (args.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"questions": len(rows), "model_calls": 0, "output": str(args.out)}))


if __name__ == "__main__":
    main()
