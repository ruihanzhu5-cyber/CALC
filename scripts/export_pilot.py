"""Export native development-pilot artifacts without reading labels or grading.

Full exports require every method/task process to have completed. Explicit
method/query selections produce a labelled subset, never a complete result set.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

METHODS = ("main", "porchestra", "clm", "dynaflow", "joint")
OFFICIAL_FIELDS = ("query_id", "tool_call_counts", "status", "retrieved_docids", "result")


class Sources:
    def __init__(self) -> None:
        self.paths: set[Path] = set()

    def json(self, path: Path) -> Any:
        self.paths.add(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def lines(self, path: Path) -> list[dict]:
        self.paths.add(path)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def hashes(self) -> list[dict]:
        return [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(self.paths)]


def docids(value: Any) -> set[str]:
    """Read source identities from structured tool observations, never prose."""
    found: set[str] = set()
    if isinstance(value, dict):
        if value.get("docid") is not None:
            found.add(str(value["docid"]))
        for child in value.values():
            found.update(docids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(docids(child))
    return found


def local_tool_docids(value: Any) -> tuple[set[str], bool]:
    """Decode structured JSON RPC envelopes; never infer identifiers from prose."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return set(), True
        if not isinstance(value, (dict, list)):
            return set(), True
    found: set[str] = set()
    incomplete = False
    if isinstance(value, dict):
        if value.get("docid") is not None:
            found.add(str(value["docid"]))
        for key, child in value.items():
            if isinstance(child, (dict, list)) or (
                key in {"body", "result", "observation", "response"} and isinstance(child, str)
            ):
                ids, lost = local_tool_docids(child)
                found.update(ids)
                incomplete |= lost
    elif isinstance(value, list):
        for child in value:
            ids, lost = local_tool_docids(child)
            found.update(ids)
            incomplete |= lost
    else:
        incomplete = True
    return found, incomplete


def result(qid: str, text: str, status: str, counts: dict, retrieved: set[str]) -> dict:
    return {"query_id": qid, "tool_call_counts": counts, "status": status,
            "retrieved_docids": sorted(retrieved),
            "result": [{"type": "output_text", "output": text}] if text.strip() else []}


def normalize(value: dict, qid: str) -> dict:
    if str(value.get("query_id")) != qid:
        raise ValueError(f"Native result identity does not match {qid}")
    if any(field not in value for field in OFFICIAL_FIELDS):
        raise ValueError(f"Incomplete official-schema result for {qid}")
    output = {field: value[field] for field in OFFICIAL_FIELDS}
    if not isinstance(output["status"], str) or not output["status"]:
        raise ValueError("Native status must be explicit")
    if not isinstance(output["tool_call_counts"], dict) or any(
        type(count) is not int or count < 0 for count in output["tool_call_counts"].values()
    ):
        raise ValueError("Tool counts must be nonnegative integers")
    if not isinstance(output["retrieved_docids"], list) or not isinstance(output["result"], list):
        raise ValueError("Native document IDs and result must be lists")
    output["retrieved_docids"] = sorted({str(key) for key in output["retrieved_docids"]})
    return output


def clm_exporter():
    path = Path(__file__).parent / "baselines/clm/calc_clm_port/export_run.py"
    spec = importlib.util.spec_from_file_location("pilot_native_clm_export", path)
    if spec is None or spec.loader is None:
        raise ImportError("CLM native exporter is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export


def convert(root: Path, run: Path, tag: str, method: str, qid: str) -> tuple[dict, dict]:
    sources = Sources()
    incomplete = False
    metadata: dict[str, Any] = {}
    if method in {"main", "joint"}:
        files = sorted((run / method / qid / "runs").glob("*.json"))
        if len(files) != 1:
            raise FileNotFoundError(f"Expected exactly one native {method}/{qid}/runs/*.json; found {len(files)}")
        output = normalize(sources.json(files[0]), qid)
    elif method == "porchestra":
        directory = run / method / qid / qid
        native = sources.json(directory / "result.json")
        if str(native.get("query_id")) != qid:
            raise ValueError("POrchestra query identity mismatch")
        counts = {"search": 0, "get_document": 0}
        retrieved: set[str] = set()
        for record in sources.lines(directory / "trace.jsonl"):
            if record.get("event_type", record.get("event")) != "bcp_tool":
                continue
            action = record.get("action") or {}
            name = action.get("action") if isinstance(action, dict) else action
            if name in counts:
                counts[name] += 1
                if "observation" not in record:
                    incomplete = True
                retrieved.update(docids(record.get("observation")))
        if native.get("tool_calls") is not None and sum(counts.values()) != native["tool_calls"]:
            incomplete = True
        text = native.get("answer") or ""
        status = "runtime_error" if native.get("error") else (
            "completed" if native.get("submitted") and text.strip() else "not_submitted")
        metadata["native_error"] = native.get("error")
        output = result(qid, text, status, counts, retrieved)
    elif method == "clm":
        tasks = root / "upstreams/CLM/calc_port/tasks_first20"
        manifest = sources.json(tasks / "manifest.json")
        row = next((item for item in manifest["tasks"] if str(item["query_id"]) == qid), None)
        if row is None:
            raise ValueError(f"CLM task manifest has no {qid}")
        task = tasks / row["directory"]
        sources.json(task / "query.json")
        trial = run / "clm-native" / f"{tag}-clm-{qid}"
        native = sources.json(trial / "result.json")
        output = normalize(clm_exporter()(trial, task), qid)
        for path in [trial / "verifier/answer.txt", trial / "agent/bcp_tools.jsonl"]:
            if path.is_file():
                sources.paths.add(path)
        incomplete = not (trial / "agent/bcp_tools.jsonl").is_file()
        if native.get("exception_info"):
            output["status"] = "runtime_error"
            metadata["native_exception_type"] = native["exception_info"].get("exception_type")
    elif method == "dynaflow":
        directory = run / "dynaflow-prepared" / qid / "run"
        native = sources.json(directory / "results/question-001.json")
        if str(native.get("task_id")) != qid:
            raise ValueError("DynaFlow task identity mismatch")
        counts = {"search": 0, "get_document": 0}
        retrieved = set()
        # These are per-task logs. Never consult the shared bridge's audit log.
        logs = sorted((directory / "workflows/question-001").glob("*/tools.jsonl"))
        if not logs:
            logs = sorted((directory / "tools").rglob("*.jsonl"))
        starts: set[str] = set()
        ends: set[str] = set()
        for path in logs:
            for index, record in enumerate(sources.lines(path)):
                if record.get("name") not in counts:
                    continue
                call_id = str(record.get("call_id", f"{path}:{index}"))
                if record.get("phase") == "start" and call_id not in starts:
                    starts.add(call_id)
                    counts[record["name"]] += 1
                elif record.get("phase") == "end":
                    ends.add(call_id)
                    if "result" in record:
                        ids, lost = local_tool_docids(record["result"])
                        retrieved.update(ids)
                        incomplete |= lost
                    elif not record.get("error_type"):
                        incomplete = True
        incomplete |= bool(starts - ends) or (not logs and native.get("selected_route") != "direct")
        text = native.get("Final answer") or ""
        valid = native.get("evaluation_valid") is True and not native.get("error")
        status = "completed" if valid and text.strip() else ("no_answer" if valid else "invalid_execution")
        output = result(qid, text, status, counts, retrieved)
        metadata.update(native_evaluation_valid=native.get("evaluation_valid"), native_error=native.get("error"))
    else:
        raise ValueError(f"Unknown method {method}")
    output = normalize(output, qid)
    if incomplete:
        output["retrieval_metrics_incomplete"] = True
    return output, {"sources": sources.hashes(), "retrieval_metrics_incomplete": incomplete, **metadata}


def export_pilot(root: Path, run_tag: str, *, limit: int = 5,
                 methods: list[str] | None = None, query_ids: list[str] | None = None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_tag) or not 1 <= limit <= 20:
        raise ValueError("Invalid run tag or frozen-task limit")
    methods = list(METHODS) if methods is None else methods
    if not methods or len(set(methods)) != len(methods) or set(methods) - set(METHODS):
        raise ValueError("Select distinct known methods")
    task_path = root / "bench/browsecomp-plus/tasks/first20.dev.jsonl"
    rows = [json.loads(line) for line in task_path.read_text().splitlines() if line.strip()]
    if len(rows) < limit or any(set(row) != {"query_id", "query"} for row in rows):
        raise ValueError("Frozen input must contain only query_id/query and enough tasks")
    frozen = [str(row["query_id"]) for row in rows[:limit]]
    selected = frozen if query_ids is None else query_ids
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(frozen):
        raise ValueError("Query subset must belong to the frozen prefix")
    subset = limit != 5 or set(methods) != set(METHODS) or set(selected) != set(frozen)
    run = root / "runs" / run_tag
    queue_path = run / "queue.json"
    queue_raw = queue_path.read_bytes()
    queue = json.loads(queue_raw)
    artifacts = []
    # Gather/validate everything before writing any full-export result.
    for method in methods:
        for qid in selected:
            job = queue.get("jobs", {}).get(f"{method}/{qid}", {})
            allowed = {"process_completed", "process_error"} if subset else {"process_completed"}
            if job.get("status") not in allowed:
                raise ValueError(f"{method}/{qid} is not exportable: queue status={job.get('status', 'missing')}")
            output, provenance = convert(root, run, run_tag, method, qid)
            artifacts.append((method, qid, output, {"queue_status": job["status"], **provenance}))
    target = run / "official"
    manifest = {"run_tag": run_tag, "scope": "subset" if subset else "full",
                "evaluation": "not_run", "methods": methods, "query_ids": selected,
                "expected_files": len(methods) * len(selected), "exports": [],
                "task_file_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
                "queue": {"path": str(queue_path), "sha256": hashlib.sha256(queue_raw).hexdigest()}}
    for method, qid, output, provenance in artifacts:
        path = target / method / f"run_{qid}.json"
        raw = (json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode()
        if path.exists() and path.read_bytes() != raw:
            raise FileExistsError(f"Refusing to replace a different export: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        manifest["exports"].append({"method": method, "query_id": qid, "status": output["status"],
                                    "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                                    "tool_call_counts": output["tool_call_counts"],
                                    "retrieved_docid_count": len(output["retrieved_docids"]), **provenance})
    target.mkdir(parents=True, exist_ok=True)
    selector = ".".join(["-".join(methods), "-".join(selected)])
    name = "exportmanifest.json" if not subset else f"exportmanifest.subset.{selector}.json"
    manifest["manifest_path"] = str(target / name)
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (target / name).write_text(text, encoding="utf-8")
    if subset:
        # Convenience pointer; each method/query subset also has its own durable manifest.
        (target / "exportmanifest.subset.json").write_text(text, encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--methods", nargs="+", choices=METHODS)
    parser.add_argument("--query-id", action="append")
    args = parser.parse_args()
    manifest = export_pilot(args.root, args.run_tag, limit=args.limit,
                            methods=args.methods, query_ids=args.query_id)
    print(json.dumps({"scope": manifest["scope"], "exported_files": len(manifest["exports"]),
                      "manifest_path": manifest["manifest_path"], "evaluation": "not_run"}))


if __name__ == "__main__":
    main()
