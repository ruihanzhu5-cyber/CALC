#!/usr/bin/env bash
# No model and no judge calls. Only schema validation, Docker and local corpus I/O.
set -euo pipefail
ROOT=/mnt/d/CALC-experiments/upstreams/CLM
ENVROOT=/opt/calc/envs/clm
export PYTHONPATH="$ROOT/calc_port"
export TMPDIR=/opt/calc/tmp/clm
export TIKTOKEN_CACHE_DIR=/opt/calc/cache/tiktoken
export LITELLM_LOCAL_MODEL_COST_MAP=True
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$ROOT/calc_port/preflight_logs"
"$ENVROOT/bin/python" -m pytest -q -p no:cacheprovider \
  "$ROOT/calc_port/tests/test_port.py" "$ROOT/clm/tests/test_context_string.py"
"$ENVROOT/bin/python" -c '
import json
from pathlib import Path
from harbor.models.task.task import Task
root=Path("/mnt/d/CALC-experiments/upstreams/CLM/calc_port/tasks_first20")
manifest=json.loads((root/"manifest.json").read_text())
for item in manifest["tasks"]:
    task=Task(root/item["directory"])
    assert task.config.metadata["evaluation"] == "external_official_judge_required"
print(json.dumps({"validated_harbor_tasks":len(manifest["tasks"]),"model_calls":0}))
'
docker build -t calc-clm-bcp:preflight "$ROOT/calc_port/tasks_first20/bcp-177-8cd25102/environment"
docker run --rm --network host calc-clm-bcp:preflight python3 -c '
import json,subprocess
response=json.loads(subprocess.check_output(["search","historical painting museum"],text=True))
docs=response["result"]
summary={"search_results":len(docs),"model_calls":0}
if docs:
    docid=str(docs[0]["docid"])
    reader=json.loads(subprocess.check_output(["get_document",docid],text=True))
    summary.update(reader_docid=reader["document"].get("docid"),reader_truncated=reader.get("truncated"))
print(json.dumps(summary))
'

"$ENVROOT/bin/harbor" trial start \
  -p "$ROOT/calc_port/tasks_first20/bcp-177-8cd25102" -e docker \
  -a calc_clm_port.preflight_agent:ContextPreflightAgent \
  --trials-dir "$ROOT/calc_port/preflight_logs" --trial-name "clm-context-no-model-$(date +%Y%m%d-%H%M%S)"
