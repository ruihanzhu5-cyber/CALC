"""Export one native Harbor CLM trial to BCP's result schema without grading it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def export(trial: Path, task: Path) -> dict:
    question = json.loads((task / "query.json").read_text())
    marker = trial / "agent" / "offline_preflight.json"
    if marker.exists():
        raise ValueError("An offline environment preflight is not a BCP model rollout")
    answer = trial / "verifier" / "answer.txt"
    text = answer.read_text(encoding="utf-8") if answer.is_file() else ""
    counts = {"search": 0, "get_document": 0}
    retrieved = set()
    tools = trial / "agent" / "bcp_tools.jsonl"
    if tools.is_file():
        for line in tools.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            action = record.get("action")
            if action in counts:
                counts[action] += 1
            retrieved.update(str(docid) for docid in record.get("docids", []))
            if record.get("docid") is not None:
                retrieved.add(str(record["docid"]))
    return {
        "query_id": str(question["query_id"]), "tool_call_counts": counts,
        "status": "completed" if text.strip() else "no_answer",
        "retrieved_docids": sorted(retrieved),
        "result": [{"type": "output_text", "output": text}] if text.strip() else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite a result")
    result = export(args.trial, args.task)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"query_id": result["query_id"], "status": result["status"], "evaluation": "not_run"}))


if __name__ == "__main__":
    main()
