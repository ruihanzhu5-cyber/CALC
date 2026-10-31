import importlib.util
import json
from pathlib import Path
import sys


scripts = Path(__file__).parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("native_retries", scripts / "run_native_retries.py")
native = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(scripts))
try:
    spec.loader.exec_module(native)
finally:
    sys.path.pop(0)


def test_retry_selection_retains_incorrect_submitted_answer(tmp_path):
    ids = ["177", "717", "263", "501", "513"]
    preserved = {"main/263", "porchestra/263", "porchestra/717", "clm/177", "clm/501", "joint/263"}
    for method in native.METHODS:
        folder = tmp_path / "evals" / method
        folder.mkdir(parents=True)
        (folder / "evaluation_summary.json").write_text(json.dumps({"evaluation": "complete", "num_judge_errors": 0}))
        for qid in ids:
            complete = f"{method}/{qid}" in preserved
            value = {"query_id": qid, "status": "judged" if complete else "incomplete_agent_response",
                     "judge_result": {"correct": complete and f"{method}/{qid}" != "clm/177"}}
            (folder / f"run_{qid}_eval.json").write_text(json.dumps(value))
    retained, retry = native.select_retries(tmp_path, ids)
    assert {f"{r['method']}/{r['query_id']}" for r in retained} == preserved
    assert len(retry) == 19
    assert not ({f"{r['method']}/{r['query_id']}" for r in retry} & preserved)


def test_recovery_retains_wrong_new_submission(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "convert", lambda *args: (
        {"status": "completed", "result": [{"type": "output_text", "output": "wrong but submitted"}]}, {}))
    path = tmp_path / "runs/interrupted/evals/main/run_177_eval.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "judged", "judge_result": {"correct": False}}))
    retained, retry = native.retain_recovery_submissions(tmp_path, "interrupted", [], [{"method": "main", "query_id": "177"}])
    assert retry == []
    assert retained[0]["source_eval_sha256"]
    assert retained[0]["retained_from_recovery"] == "interrupted"


def test_prebuilt_clm_preserves_task_inputs_and_resource_limits(tmp_path):
    source = tmp_path / "original"
    (source / "environment").mkdir(parents=True)
    (source / "instruction.md").write_text("Public task")
    (source / "task.toml").write_text('[environment]\ncpus = 1\nmemory_mb = 1024\n')
    (source / "environment/docker-compose.yaml").write_text(
        'services:\n  main:\n    build:\n      context: .\n      dockerfile: Dockerfile\n'
        '    image: ${MAIN_IMAGE_NAME}\n    network_mode: host\n')
    image = "sha256:" + "a" * 64
    job = {"command": ["bash", "launcher", str(source)]}
    native.use_prebuilt_clm_task(tmp_path, "recovered", job, image)
    target = Path(job["command"][2])
    assert (target / "instruction.md").read_bytes() == (source / "instruction.md").read_bytes()
    assert 'memory_mb = 1024' in (target / "task.toml").read_text()
    assert image in (target / "task.toml").read_text()
    compose = (target / "environment/docker-compose.yaml").read_text()
    assert "build:" not in compose
    assert "${PREBUILT_IMAGE_NAME}" in compose
    assert "network_mode: host" in compose


def test_recovery_does_not_retain_tool_protocol_mislabeled_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "convert", lambda *args: (
        {"status": "completed", "result": [{"output": '<｜｜DSML｜｜ calls>pending'}]}, {}))
    row = {"method": "main", "query_id": "177"}
    retained, retry = native.retain_recovery_submissions(tmp_path, "interrupted", [], [row])
    assert retained == [] and retry == [row]
