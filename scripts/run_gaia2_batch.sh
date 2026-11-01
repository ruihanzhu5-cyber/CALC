#!/usr/bin/env bash
set -euo pipefail
cd /mnt/d/CALC-experiments/code/CALC-task-progress
export PYTHONPATH=/mnt/d/CALC-experiments/code/CALC-task-progress/src
export TMPDIR=/opt/calc/tmp HF_HOME=/opt/calc/cache/huggingface
export XDG_CACHE_HOME=/opt/calc/cache PYTHONDONTWRITEBYTECODE=1
exec /opt/calc/envs/gaia2/bin/python -u scripts/run_gaia2_batch.py --config configs/adaptive.gaia2.pilot5.json --execute
