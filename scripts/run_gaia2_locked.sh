#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
export TMPDIR=/opt/calc/tmp HF_HOME=/opt/calc/cache/huggingface
export XDG_CACHE_HOME=/opt/calc/cache PYTHONDONTWRITEBYTECODE=1
exec /opt/calc/envs/gaia2/bin/python -u scripts/run_gaia2_batch.py "$@"
