from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_pilot.py"
SPEC = importlib.util.spec_from_file_location("pilot_export_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def write(path: Path, value, *, lines=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row) for row in value) if lines else json.dumps(value)
    path.write_text(text + "\n", encoding="utf-8")


def setup_native(root: Path):
    tag = "dev5-flash-1m-v0"
    run = root / "runs" / tag
    write(root / "bench/browsecomp-plus/tasks/first20.dev.jsonl",
          [{"query_id": "177", "query": "Question?"}], lines=True)
    write(run / "queue.json", {"jobs": {f"{method}/177": {"status": "process_completed"}
                                        for method in pilot.METHODS}})
    canonical = {"query_id": "177", "tool_call_counts": {"search": 1, "get_document": 0},
                 "status": "token_budget", "retrieved_docids": ["m1"], "result": []}
    write(run / "main/177/runs/run_native.json", canonical)
    write(run / "joint/177/runs/run_native.json", {
        **canonical, "status": "completed", "result": [{"type": "output_text", "output": "Fixture answer"}]})
    write(run / "porchestra/177/177/result.json", {
        "query_id": "177", "answer": "", "submitted": False, "error": "Fixture transport failure", "tool_calls": 1})
    write(run / "porchestra/177/177/trace.jsonl", [{
        "event_type": "bcp_tool", "action": {"action": "search", "params": {"query": "query"}},
        "observation": {"result": [{"docid": "p1", "document": {"text": "Fixture source"}}]}}], lines=True)
    tasks = root / "upstreams/CLM/calc_port/tasks_first20"
    write(tasks / "manifest.json", {"tasks": [{"query_id": "177", "directory": "task-177"}]})
    write(tasks / "task-177/query.json", {"query_id": "177", "query": "Question?"})
    trial = run / "clm-native" / f"{tag}-clm-177"
    write(trial / "result.json", {"exception_info": {"exception_type": "FixtureError"}})
    write(trial / "agent/bcp_tools.jsonl", [{"action": "search", "docids": ["c1"]}], lines=True)
    native = run / "dynaflow-prepared/177/run"
    write(native / "results/question-001.json", {
        "task_id": "177", "evaluation_valid": False, "Final answer": "Partial fixture answer",
        "error": "Fixture execution failure", "search_calls": 0, "selected_route": "workflow"})
    write(native / "workflows/question-001/session/tools.jsonl", [
        {"phase": "start", "name": "search", "call_id": "tool-1", "arguments": {"query": "query"}},
        {"phase": "end", "name": "search", "call_id": "tool-1", "result": {
            "result": [{"docid": "d1", "document": {"text": "Source text"}}]}},
        {"phase": "start", "name": "get_document", "call_id": "tool-2", "arguments": {"docid": "d1"}},
        {"phase": "end", "name": "get_document", "call_id": "tool-2", "result": {
            "document": {"docid": "d1", "text": "Longer original source"}}},
    ], lines=True)
    return tag, run


def expand_five(root: Path, tag: str, run: Path):
    qids = ["177", "717", "263", "501", "513"]
    write(root / "bench/browsecomp-plus/tasks/first20.dev.jsonl",
          [{"query_id": qid, "query": "Question?"} for qid in qids], lines=True)
    write(run / "queue.json", {"jobs": {f"{method}/{qid}": {"status": "process_completed"}
                                        for method in pilot.METHODS for qid in qids}})
    tasks = root / "upstreams/CLM/calc_port/tasks_first20"
    write(tasks / "manifest.json", {"tasks": [{"query_id": qid, "directory": f"task-{qid}"} for qid in qids]})
    for qid in qids[1:]:
        pairs = [(run / method / "177", run / method / qid) for method in ("main", "joint", "porchestra")]
        pairs.extend([(run / "dynaflow-prepared/177", run / "dynaflow-prepared" / qid),
                      (run / "clm-native" / f"{tag}-clm-177", run / "clm-native" / f"{tag}-clm-{qid}"),
                      (tasks / "task-177", tasks / f"task-{qid}")])
        for source, target in pairs:
            shutil.copytree(source, target)
            for path in target.rglob("*.json"):
                path.write_text(path.read_text().replace('"177"', json.dumps(qid)))
        # Native POrchestra adds its own query directory below the queue output.
        (run / "porchestra" / qid / "177").rename(run / "porchestra" / qid / qid)


def test_full_export_preserves_failures_and_uses_native_tool_observations(tmp_path):
    tag, run = setup_native(tmp_path)
    expand_five(tmp_path, tag, run)
    manifest = pilot.export_pilot(tmp_path, tag, limit=5)
    assert manifest["scope"] == "full" and len(manifest["exports"]) == 25
    values = {method: json.loads((run / "official" / method / "run_177.json").read_text())
              for method in pilot.METHODS}
    assert values["main"]["status"] == "token_budget" and values["main"]["result"] == []
    assert values["porchestra"]["status"] == "runtime_error"
    assert values["porchestra"]["retrieved_docids"] == ["p1"]
    assert values["clm"]["status"] == "runtime_error" and values["clm"]["result"] == []
    assert values["clm"]["retrieved_docids"] == ["c1"]
    assert values["dynaflow"]["status"] == "invalid_execution"
    assert values["dynaflow"]["result"][0]["output"] == "Partial fixture answer"
    assert values["dynaflow"]["tool_call_counts"] == {"search": 1, "get_document": 1}
    assert values["dynaflow"]["retrieved_docids"] == ["d1"]
    assert values["joint"]["status"] == "completed"
    for item in manifest["exports"]:
        assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]
        assert item["sources"]
        for source in item["sources"]:
            assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]


def test_missing_artifact_or_unfinished_queue_cannot_create_full_export(tmp_path):
    tag, run = setup_native(tmp_path)
    expand_five(tmp_path, tag, run)
    source = run / "main/177/runs/run_native.json"
    original = source.read_bytes()
    source.unlink()
    with pytest.raises(FileNotFoundError, match="Expected exactly one"):
        pilot.export_pilot(tmp_path, tag, limit=5)
    assert not (run / "official").exists()
    source.write_bytes(original)
    queue = json.loads((run / "queue.json").read_text())
    queue["jobs"]["dynaflow/177"]["status"] = "running"
    write(run / "queue.json", queue)
    with pytest.raises(ValueError, match="queue status=running"):
        pilot.export_pilot(tmp_path, tag, limit=5)
    assert not (run / "official").exists()


def test_subset_is_explicit_and_retains_a_process_failure(tmp_path):
    tag, run = setup_native(tmp_path)
    queue = json.loads((run / "queue.json").read_text())
    queue["jobs"]["main/177"]["status"] = "process_error"
    write(run / "queue.json", queue)
    manifest = pilot.export_pilot(tmp_path, tag, limit=1, methods=["main"], query_ids=["177"])
    assert manifest["scope"] == "subset" and manifest["expected_files"] == 1
    assert manifest["exports"][0]["queue_status"] == "process_error"
    assert manifest["exports"][0]["status"] == "token_budget"
    assert not (run / "official/exportmanifest.json").exists()
    assert (run / "official/exportmanifest.subset.json").is_file()
    assert Path(manifest["manifest_path"]).name == "exportmanifest.subset.main.177.json"
    assert Path(manifest["manifest_path"]).is_file()


def test_dynaflow_missing_local_tools_marks_retrieval_incomplete(tmp_path):
    tag, run = setup_native(tmp_path)
    (run / "dynaflow-prepared/177/run/workflows/question-001/session/tools.jsonl").unlink()
    manifest = pilot.export_pilot(tmp_path, tag, limit=1, methods=["dynaflow"])
    exported = json.loads((run / "official/dynaflow/run_177.json").read_text())
    assert exported["retrieval_metrics_incomplete"] is True
    assert manifest["exports"][0]["retrieval_metrics_incomplete"] is True
    assert exported["retrieved_docids"] == []


@pytest.mark.parametrize("value, expected_ids, incomplete", [
    (json.dumps({"result": [{"docid": "encoded-id"}]}), {"encoded-id"}, False),
    ({"body": json.dumps({"document": {"docid": "body-id", "text": "source"}})}, {"body-id"}, False),
    ({"body": "Unstructured response mentioning docid guess-42"}, set(), True),
    ({"document": {"docid": "real-id", "text": '{"docid":"prose-is-not-an-id"}'}}, {"real-id"}, False),
])
def test_dynaflow_tool_envelopes_decode_only_structured_ids(value, expected_ids, incomplete):
    assert pilot.local_tool_docids(value) == (expected_ids, incomplete)
