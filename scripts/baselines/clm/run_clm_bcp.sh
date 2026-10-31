#!/usr/bin/env bash
# Preparation artifact. Running this script invokes the paid model API.
set -euo pipefail
ROOT=${CLM_RUNTIME_ROOT:-/mnt/d/CALC-experiments/upstreams/CLM}
PORTROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ENVROOT=/opt/calc/envs/clm
: "${CALC_GATEWAY_KEY:?Inherit the local gateway token; do not print or write it}"
: "${CLM_API_BASE:?Set the metered per-task proxy base e.g. http://127.0.0.1:8767/v1/RUNID/QID}"
TASK=${1:?Usage: run_clm_bcp.sh HARBOR_TASK_DIRECTORY [extra harbor args]}
shift
export PYTHONPATH="$PORTROOT${PYTHONPATH:+:$PYTHONPATH}"
export TEMP=/opt/calc/tmp/clm
export TMPDIR="$TEMP"
export UV_CACHE_DIR=/mnt/d/CALC-experiments/cache/uv
export PIP_CACHE_DIR=/mnt/d/CALC-experiments/cache/pip
export HF_HOME=/mnt/d/CALC-experiments/cache/hf
export TIKTOKEN_CACHE_DIR=/opt/calc/cache/tiktoken
export LITELLM_LOCAL_MODEL_COST_MAP=True
export CLM_EDIT_GATE=shrink
export CLM_LLM_MAX_RETRIES=1
mkdir -p "$TEMP"
exec "$ENVROOT/bin/harbor" trial start -p "$TASK" -e docker \
  -a calc_clm_port.agent:DeepSeekClmAgent -m openai/deepseek-flash \
  --agent-kwarg "api_base=$CLM_API_BASE" \
  --agent-kwarg context_budget_tokens=28672 \
  --agent-kwarg context_budget_reserve_tokens=2048 \
  --agent-kwarg "max_tokens=${CALC_MAX_OUTPUT_TOKENS:-4096}" --agent-kwarg max_steps=500 \
  --agent-kwarg lm_call_cap=100 --agent-kwarg cost_metric=usd \
  --agent-kwarg persistent_bash=true --agent-kwarg observation_max_chars=60000 \
  --agent-kwarg persistent_nudge_ratio=0.9 --agent-kwarg max_num_retry_on_limit=6 \
  --agent-kwarg task_template=open_problems --agent-kwarg max_transport_attempts=1 \
  --trials-dir "${CLM_TRIALS_DIR:-$ROOT/calc_port/trials}" "$@"
