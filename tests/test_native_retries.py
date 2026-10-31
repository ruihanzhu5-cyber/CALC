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
