#!/usr/bin/env bash
# One user-authorized recovery attempt; never restart paid actors automatically.
set -euo pipefail
source /mnt/d/CALC-experiments/code/CALC/scripts/experiment_env.sh
tag=${1:?new run tag required}
recovery=${2:?interrupted run tag required}
[[ "$tag" =~ ^[A-Za-z0-9_.-]+$ && "$recovery" =~ ^[A-Za-z0-9_.-]+$ ]]
repo="$CALC_EXPERIMENT_ROOT/code/CALC"
run="$CALC_EXPERIMENT_ROOT/runs/$tag"
mkdir -p "$run"
cd "$repo"
if ! curl --noproxy '*' -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; then
  systemd-run --unit=calc-retriever --collect \
    --property=StandardOutput=append:"$CALC_EXPERIMENT_ROOT/bench/browsecomp-plus/service.log" \
    --property=StandardError=inherit bash "$repo/scripts/baselines/browsecomp/start_service.sh"
fi
if ! curl --noproxy '*' -fsS http://127.0.0.1:8766/ready >/dev/null 2>&1; then
  systemd-run --unit=calc-dynaflow-bridge --collect \
    --property=StandardOutput=append:"$CALC_EXPERIMENT_ROOT/runs/services/dynaflow-bridge.stdout.log" \
    --property=StandardError=inherit /opt/calc/envs/calc/bin/python \
    "$repo/scripts/baselines/dynaflow/bridge.py" --upstream http://127.0.0.1:8765 \
    --log "$CALC_EXPERIMENT_ROOT/runs/services/dynaflow-bridge-tools.jsonl"
fi
python - <<'PY'
import time, httpx, json
from pathlib import Path
with httpx.Client(timeout=120,trust_env=False) as c:
    for _ in range(120):
        try:
            c.get('http://127.0.0.1:8765/health').raise_for_status()
            c.get('http://127.0.0.1:8766/ready').raise_for_status()
            break
        except httpx.HTTPError:
            time.sleep(1)
    else:
        raise RuntimeError('Corpus services unavailable; no model calls launched')
    task=json.loads(Path('/mnt/d/CALC-experiments/bench/browsecomp-plus/tasks/first20.dev.jsonl').read_text().splitlines()[0])
    rows=c.post('http://127.0.0.1:8765/retrieve',json={'query':task['query']}).raise_for_status().json()['result']
    assert rows
    assert c.post('http://127.0.0.1:8765/document',json={'docid':rows[0]['docid']}).raise_for_status().json()['document']
print('Actual corpus search and document preflight passed; no model calls')
PY
env_dir="$CALC_EXPERIMENT_ROOT/upstreams/CLM/calc_port/tasks_first20/bcp-717-d536a8c1/environment"
# Verify all CLM build inputs are identical before reusing the image.
python - <<'PY'
import hashlib
from pathlib import Path
root=Path('/mnt/d/CALC-experiments/upstreams/CLM/calc_port/tasks_first20')
for name in ('Dockerfile','bcp_tools.py'):
    digests={hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob(f'bcp-*/environment/{name}')}
    assert len(digests)==1, (name,'different environment inputs')
PY
docker build -t "calc-clm-bcp:$tag" "$env_dir" > "$run/clm-image-build.log" 2>&1
image=$(docker image inspect "calc-clm-bcp:$tag" --format '{{.Id}}')
printf '%s\n' "$image" > "$run/clm-image-id.txt"
docker run --rm --network host "$image" python3 -c \
  'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8765/health",timeout=15).status==200; print("Prebuilt CLM container reaches corpus service")'
PYTHONPATH=/opt/calc/upstreams/DynaFlow/src python scripts/baselines/dynaflow/prepare_shards.py \
  --tasks "$CALC_EXPERIMENT_ROOT/bench/browsecomp-plus/tasks/first20.dev.jsonl" \
  --out "$run/dynaflow-prepared" --run-tag "$tag" --limit 5 --native-settings \
  --max-output 65536 --deadline 0 --max-model-requests 0 --observed-token-stop-threshold 0
# systemd owns all descendants; --wait keeps the host's WSL session active.
# No Restart policy: an interrupted paid attempt always requires an explicit recovery.
env_file="/run/calc/actors-$tag.env"
trap 'rm -f -- "$env_file"' EXIT
python scripts/write_service_environment.py "$env_file" CALC_GATEWAY_KEY PATH PYTHONPATH
systemd-run --unit="calc-actors-$tag" --collect --wait --pipe \
  --property=WorkingDirectory="$repo" --property=KillMode=mixed \
  --property=EnvironmentFile="$env_file" \
  /opt/calc/envs/calc/bin/python scripts/run_native_retries.py \
  --run-tag "$tag" --recovery-run "$recovery" --concurrency 19 \
  --clm-prebuilt-image "$image" --execute
